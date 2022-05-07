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
    name: str
    expirydate: datetime.datetime = None
    registrationdate: datetime.datetime = None
    # daysold: float = None
    
    # Generated 
    _hexid: str = None
    _decid: int = None
    _gracedate: datetime.datetime = None
    _premiumdate: datetime.datetime = None
    _enstype: ENSType = None
    _premium: float = None
    
    # Get Hex and Decimal ID
    def __post_init__(self):
        hexid, decid = getids(self.name)
        self._hexid = hexid
        self._decid = decid
        if self.registrationdate or self.expirydate:
            self._gracedate = self.expirydate + datetime.timedelta(days=90.0)
            self._premiumdate = self.expirydate + datetime.timedelta(days=111.0)
            daysold = (datetime.datetime.now() - self.expirydate).days
            if daysold > 111: self._enstype = ENSType.EXPIRED
            elif daysold > 90:
                self._enstype = ENSType.PREMIUM
                # Premium Exponential Decay Formula
                self._premium = 100_000_000 * (0.5 ** (daysold-90))
            elif daysold > 0: self._enstype = ENSType.GRACE
            else: self._enstype = ENSType.OWNED
        else:
            self._enstype = ENSType.NEW

    # Get line string for csv output
    def getcsv(self):
        attrs = [self.name,
                 len(self.name),
                 self._enstype.value,
                 self._premium,
                 self.registrationdate,
                 self.expirydate,
                 self._gracedate,
                 self._premiumdate,
                 self._hexid,
                 self._decid,
                 f"'{self._decid}'"]
        return ",".join([str(i) if i else '' for i in attrs])

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
    # Add New Domains
    returnednames = [word["labelName"] for word in domaindata]
    domains = [ENSListing(word) for word in words if word not in returnednames]
    # Add Other Domains
    def generateenslisting(entry: dict):
        name = entry["labelName"]
        expirydt = datetime.datetime.fromtimestamp(float(entry["expiryDate"]))
        registrationdt = datetime.datetime.fromtimestamp(float(entry["registrationDate"]))
        return ENSListing(name, expirydt, registrationdt)
    domains += [generateenslisting(entry) for entry in domaindata]
    return domains

def makeoutputdir():
    if not os.path.exists("./output"): os.mkdir("./output")
    if not os.path.exists("./output/letters"): os.mkdir("./output/letters")

# Saves a text file with all the non-premium words
def saveavailable(domains: list[ENSListing]):
    domains.sort(key=lambda x: len(x.name))
    enslist = [i.name for i in domains if i._enstype is ENSType.NEW or i._enstype is ENSType.EXPIRED]
    with open(f"./output/{AVAILABLE}.txt", 'w') as file:
        file.write("\n".join(enslist))

# Saves a CSV containing data for all of the domains provided
def savemaincsv(domains: list[ENSListing]):
    domains.sort(key=lambda x: x.registrationdate if x.registrationdate else datetime.datetime.fromtimestamp(0))
    domains.sort(key=lambda x: x._enstype.value)
    enslist = ["Name,Length,Status,Premium,Registered,Expires,Grace Period Ends,Price Premium Ends,Hex Token ID,Decimal Token ID,Decimal Token ID Repr"]
    enslist += [i.getcsv() for i in domains]
    with open(f"./output/{NAMES}.csv", 'w') as file:
        file.write("\n".join(enslist))

# Saves valid words and words seperated by length
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

# Print summary information
def summaryprint(start: datetime.datetime,
                 words: list[str],
                 numinvalid: int,
                 domainobjs: list[ENSListing]):
    numpremium = len([d for d in domainobjs if d._enstype is ENSType.PREMIUM])
    numvalid = len(words)
    numavailable = len([i.name for i in domainobjs if i._enstype is ENSType.NEW or i._enstype is ENSType.EXPIRED])
    totalwords = numvalid+numinvalid
    elapsed = (datetime.datetime.now() - start).total_seconds()
    pastday = len(['' for i in domainobjs if i.registrationdate and i.registrationdate > (datetime.datetime.now()-datetime.timedelta(days=1))])
    print(f"ENS bulk search completed in {elapsed:.2f} seconds. "
          "Files have been outputted to ./output\n"
          f"{totalwords} Words Searched | "
          f"{numvalid} Valid ({(numvalid*100.0)/totalwords:.2f}%) | "
          f"{numinvalid} Invalid ({(numinvalid*100.0)/totalwords:.2f}%)\n"
          f"{numavailable} Available ({(numavailable*100.0)/numvalid:.2f}%) | "
          f"{numpremium} Premium ({(numpremium*100.0)/numvalid:.2f}%) | "
          f"{pastday} registered in the past day ({(pastday*100.0)/(numavailable+pastday):.2f}% of words remaining a day ago)")

def main():
    start = datetime.datetime.now()
    words, numinvalid = getwords()
    domaindata = getlistingdata(words)
    domainobjs = getdomains(words, domaindata)
    makeoutputdir()
    saveavailable(domainobjs)
    savewords(words)
    savemaincsv(domainobjs)
    summaryprint(start, words, numinvalid, domainobjs)

if __name__ == '__main__':
    main()