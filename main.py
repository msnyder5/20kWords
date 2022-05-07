import os
import grequests
from enum import Enum
import time
import datetime
from Crypto.Hash import keccak
from dataclasses import dataclass

INPUT = './input/top20kwords.txt'
AVAILABLE = 'available'
NAMES = 'names'
LETTERS = '{} letters'
VALIDWORDS = 'validwords'


URL = "https://api.thegraph.com/subgraphs/name/ensdomains/ens"
QUERY = "\n        query getName($ids: [ID!]) {\n          registrations(where: { id_in: $ids }) {\n            id\n            labelName\n            expiryDate\n            registrationDate\n          }\n        }\n    "

# Enum to track the listing status
class ENSType(Enum):
    NEW = "Never Registered"
    EXPIRED = "Expired Registration"
    PREMIUM = "Available for Premium"
    GRACE = "On Grace Period"
    OWNED = "Currently Owned"

# Dataclass to store information about a domain
@dataclass
class ENSListing():
    enstype: ENSType
    name: str
    daysold: float = None
    premium: float = None
    hexid: str = None
    decid: int = None
    
    # Get Hex and Decimal ID
    def __post_init__(self):
        hexid, decid = getids(self.name)
        self.hexid = hexid
        self.decid = decid

    # Get line string for csv output
    def getcsv(self):
        attrs = [self.name,
                 len(self.name),
                 self.enstype.value,
                 self.premium if self.premium else '',
                 abs(self.daysold) if self.daysold else '',
                 abs(self.daysold-90.0) if self.daysold else '',
                 abs(self.daysold-111.0) if self.daysold else '',
                 self.hexid,
                 self.decid]
        return ",".join([str(i) for i in attrs])

def getids(name: str, hexonly=False):
    hasher = keccak.new(digest_bits=256)
    hasher.update(name.encode('utf-8'))
    hex = hasher.hexdigest()
    dec = int(hex, 16)
    if hexonly: return f"0x{hex}"
    return f"0x{hex}", dec

# Get a list of all of the valid words.
def getwords():
    with open(INPUT) as txtfile:
        lines = txtfile.readlines()
    words = [line[:-1] if '\n' in line else line for line in lines]
    validwords = [name for name in words if len(name) > 2]
    return validwords, len(words)-len(validwords)

# Get the data for each domain
def getlistingdata(words: list[str]):
    chunks = [words[i:i+100] for i in range(0, len(words), 100)]
    ensidslist = [[getids(i, True) for i in chunk] for chunk in chunks]
    rjsons = [{
        "query": QUERY,
        "variables": {
            "ids": ensids
        }
    } for ensids in ensidslist]
    requests = (grequests.post(url=URL, json=rjson) for rjson in rjsons)
    responses = grequests.map(requests)
    datachunks = [r.json()["data"]["registrations"] for r in responses]
    return [i for chunk in datachunks for i in chunk]

# Create the domain object for each domain
def getdomains(words: list[str], domaindata: list[dict]):
    # Current UNIX Epoch
    now = time.mktime(datetime.datetime.now().timetuple())
    # Add New Domains
    returnednames = [word["labelName"] for word in domaindata]
    domains = [ENSListing(ENSType.NEW, word) for word in words if word not in returnednames]
    # Add Other Domains
    for entry in domaindata:
        name = entry["labelName"]
        # Expiration UNIX Epoch
        expiry = int(entry["expiryDate"])
        # Days since expiration
        daysold = (now-expiry)/(24*60*60)
        premium = None
        if daysold > 111:
            enstype = ENSType.EXPIRED
        elif daysold > 90:
            enstype = ENSType.PREMIUM
            # Premium Exponential Decay Formula
            premium = 100_000_000 * (0.5 ** (daysold-90))
        elif daysold > 0:
            enstype = ENSType.GRACE
        else:
            enstype = ENSType.OWNED
        domains.append(ENSListing(enstype, name, daysold, premium))
    return domains

def makeoutputdir():
    if not os.path.exists("./output"): os.mkdir("./output")
    if not os.path.exists("./output/letters"): os.mkdir("./output/letters")

# Saves a text file with all the non-premium words
def saveavailable(domains: list[ENSListing]):
    enslist = [i.name for i in domains if i.enstype is ENSType.NEW or i.enstype is ENSType.EXPIRED]
    with open(f"./output/{AVAILABLE}.txt", 'w') as file:
        file.write("\n".join(enslist))
    return len(enslist)

# Saves a CSV containing data for all of the domains provided
def savemaincsv(domains: list[ENSListing]):
    enslist = ["Name,Length,Status,Premium,Days Since/Until Grace Period Start,Days Since/Until Grace Period End (Premium Period Start),Days Since/Until Premium Period End,Hex Token ID,Decimal Token ID"]
    enslist += [i.getcsv() for i in domains]
    with open(f"./output/{NAMES}.csv", 'w') as file:
        file.write("\n".join(enslist))

def savewords(words: list[str]):
    with open(f"./output/{VALIDWORDS}.txt", 'w') as file:
        file.write("\n".join(words))
    length = 3
    counted = 0
    total = len(words)
    while(counted < total):
        validwords = [word for word in words if len(word) == length]
        with open(f"./output/letters/{LETTERS}.txt".format(length), 'w') as file:
            file.write("\n".join(validwords))
        counted += len(validwords)
        length += 1

def main():
    words, numinvalid = getwords()
    domaindata = getlistingdata(words)
    domainobjs = getdomains(words, domaindata)
    makeoutputdir()
    numavailable = saveavailable(domainobjs)
    savemaincsv(domainobjs)
    savewords(words)
    
    numpremium = len([d for d in domainobjs if d.enstype is ENSType.PREMIUM])
    numvalid = len(words)
    totalwords = numvalid+numinvalid
    print("ENS Bulk Search completed. Files have been outputted to ./output\n"
          f"{totalwords} Words Searched | "
          f"{numvalid} Valid ({(numvalid*100.0)/totalwords:.2f}%) | "
          f"{numinvalid} Invalid ({(numinvalid*100.0)/totalwords:.2f}%)\n"
          f"{numavailable} Available ({(numavailable*100.0)/numvalid:.2f}%) | "
          f"{numpremium} Premium ({(numpremium*100.0)/numvalid:.2f}%)")

if __name__ == '__main__':
    main()