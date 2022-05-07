from collections import defaultdict
import os
import re
import grequests
from enum import Enum
import datetime
from Crypto.Hash import keccak
from dataclasses import dataclass
import config
import shutil

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
        url = f"https://opensea.io/assets/0x57f1887a8bf19b14fc0df6fd9b2acc9af147ea85/{self._decid}" if self._enstype is ENSType.OWNED else f"https://app.ens.domains/name/{self.name}.eth/register"
        attrs = [self.name,
                 len(self.name),
                 self._enstype.value,
                 self._premium,
                 url,
                 self.registrationdate,
                 self.expirydate,
                 self._gracedate,
                 self._premiumdate]
        return ",".join([str(i) if i else '' for i in attrs])

def getids(name: str, hexonly=False):
    hasher = keccak.new(digest_bits=256)
    hasher.update(name.encode('utf-8'))
    hex = hasher.hexdigest()
    dec = int(hex, 16)
    if hexonly: return f"0x{hex}"
    return f"0x{hex}", dec

# Get a list of all of the valid words.
def getwords(dirname: str):
    with open(f"./input/{dirname}.txt") as txtfile:
        lines = txtfile.readlines()
    print(f"\nBulk searching {len(lines)} words in {dirname}.txt...")
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

def sortdomains(words: list[str], domainobjs: list[ENSListing]):
    wordsranks = {d: i for i, d in enumerate(words)}
    domainobjs.sort(key=lambda x: wordsranks[x.name])
    if config.SORTBY == 2: domainobjs.sort(key=lambda x: x.name)
    elif config.SORTBY == 3: domainobjs.sort(key=lambda x: len(x.name))
    elif config.SORTBY == 4: domainobjs.sort(key=lambda x: x._enstype.value)
    elif config.SORTBY == 5: domainobjs.sort(key=lambda x: x.registrationdate or datetime.datetime.min, reverse=True)
    elif config.SORTBY == 6: domainobjs.sort(key=lambda x: x.registrationdate or datetime.datetime.max)
    elif config.SORTBY == 7: domainobjs.sort(key=lambda x: x.expirydate or datetime.datetime.min, reverse=True)
    elif config.SORTBY == 8: domainobjs.sort(key=lambda x: x.expirydate or datetime.datetime.max)
    return domainobjs

# Create the domain object for each domain
def getdomains(words: list[str], domaindata: list[dict]):
    # Add New Domains
    returnednames = [word["labelName"] for word in domaindata]
    newdomains = list(set(words) - set(returnednames))
    domains = [ENSListing(word) for word in newdomains]
    # Add Other Domains
    def generateenslisting(entry: dict):
        name = entry["labelName"]
        expirydt = datetime.datetime.fromtimestamp(float(entry["expiryDate"]))
        registrationdt = datetime.datetime.fromtimestamp(float(entry["registrationDate"]))
        return ENSListing(name, expirydt, registrationdt)
    domains += [generateenslisting(entry) for entry in domaindata]
    return sortdomains(words, domains)

def makeoutputdir(dirname: str):
    if dirname == '20kWordClub':
        if not os.path.exists("./20kWordClub"): os.mkdir("./20kWordClub")
        if not os.path.exists("./20kWordClub/length"): os.mkdir("./20kWordClub/length")
        os.chdir(f'./20kWordClub')
    else:
        if not os.path.exists("./output"): os.mkdir("./output")
        if not os.path.exists(f"./output/{dirname}"): os.mkdir(f"./output/{dirname}")
        if not os.path.exists(f"./output/{dirname}/length"): os.mkdir(f"./output/{dirname}/length")
        os.chdir(f'./output/{dirname}')

# Saves a text file with all the non-premium words
def saveavailable(domains: list[ENSListing]):
    enslist = [i.name for i in domains if i._enstype in [ENSType.NEW, ENSType.EXPIRED]]
    if not enslist: return
    with open(f"available.txt", 'w') as file:
        file.write("\n".join(enslist))

# Saves valid words and words seperated by length
def savevalid(words: list[str]):
    with open(f"valid.txt", 'w') as file:
        file.write("\n".join(words))

def savelength(words: list[str]):
    lengthdict = defaultdict(list)
    for word in words: lengthdict[len(word)].append(word)
    if not (len(words)*0.5 > len(lengthdict) > 2):
        shutil.rmtree('./length')
        return
    for i, iwords in lengthdict.items():
        with open(f"./length/{i} chars.txt", 'w') as file:
            file.write("\n".join(iwords))

# Saves a CSV containing data for all of the domains provided
def savemaincsv(domains: list[ENSListing]):
    enslist = ["Name,Length,Status,Premium,URL,Registered,Expires,Grace Period Ends,Price Premium Ends"]
    enslist += [i.getcsv() for i in domains]
    with open(f"domains.csv", 'w') as file:
        file.write("\n".join(enslist))

# Update readme and print summary
def readmeandprint(start: datetime.datetime,
                   words: list[str],
                   numinvalid: int,
                   domainobjs: list[ENSListing],
                   update = False):
    numvalid = len(words)
    numavailable = len([i.name for i in domainobjs if i._enstype is ENSType.NEW or i._enstype is ENSType.EXPIRED])
    numpremium = len([d for d in domainobjs if d._enstype is ENSType.PREMIUM])
    pastday = len(['' for i in domainobjs if i.registrationdate and i.registrationdate > (datetime.datetime.now()-datetime.timedelta(days=1))])
    elapsed = (datetime.datetime.now() - start).total_seconds()
    totalwords = numvalid+numinvalid
    if update: updatereadme(numavailable, pastday)
    printstr = (f"ENS bulk search completed in {elapsed:.2f} seconds.\n"
                f"{totalwords} Words Searched\n"
                f"{numvalid} Valid ({(numvalid*100.0)/totalwords:.2f}%)\n"
                f"{numinvalid} Invalid ({(numinvalid*100.0)/totalwords:.2f}%)\n")
    if numavailable: printstr += f"{numavailable} Available for base price ({(numavailable*100.0)/numvalid:.2f}%)\n"
    if numpremium: printstr += f"{numpremium} Available for premium price ({(numpremium*100.0)/numvalid:.2f}%)\n"
    if numavailable: printstr += f"{pastday} Registered in the past day ({(pastday*100.0)/(numavailable+pastday):.2f}%)\n"
    print(printstr)

# Autoupdate readme with new statistics (can be disabled)
def updatereadme(numavailable: int, pastday: int):
    with open("README.md", 'r', encoding='utf-16') as readme:
        rmstr = readme.read()
        rmstr = re.sub(r"As of last update, \d+ words are available, with \d+ sales in the past day",
                       f"As of last update, {numavailable} words are available, with {pastday} sales in the past day",
                       rmstr)
    with open("README.md", 'w', encoding='utf-16') as readme:
        readme.write(rmstr)

def main():
    # Getting data
    for filename in os.listdir('./input'):
        dirname = filename.removesuffix('.txt')
        start = datetime.datetime.now()
        words, numinvalid = getwords(dirname)
        domaindata = getlistingdata(words)
        domainobjs = getdomains(words, domaindata)
        # Outputs
        makeoutputdir(dirname)
        if config.AVAILABLE: saveavailable(domainobjs)
        if config.VALID and numinvalid: savevalid(words)
        if config.LENGTH: savelength(words)
        if config.CSV: savemaincsv(domainobjs)
        os.chdir('..') if dirname == '20kWordClub' else os.chdir('../..')
        update = config.README and dirname == '20kWordClub'
        readmeandprint(start, words, numinvalid, domainobjs, update)

if __name__ == '__main__':
    main()