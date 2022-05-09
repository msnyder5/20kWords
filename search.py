from collections import defaultdict
from glob import glob
import os
import re
import grequests
import requests
from requests.adapters import HTTPAdapter, Retry
from enum import Enum
import datetime
from Crypto.Hash import keccak
from dataclasses import dataclass
import config
import shutil

URL = "https://api.thegraph.com/subgraphs/name/ensdomains/ens"
QUERY = """
query getENSData($labelName_in: [String!]) {
  registrations(where: {labelName_in: $labelName_in}) {
    labelName
    expiryDate
    registrationDate
    domain {
      owner {
        id
      }
      createdAt
    }
  }
}""".strip()

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
    owner: str = None
    creationdate: datetime.datetime = None
    expirydate: datetime.datetime = None
    registrationdate: datetime.datetime = None
    # daysold: float = None
    
    # Generated 
    _gracedate: datetime.datetime = None
    _premiumdate: datetime.datetime = None
    _enstype: ENSType = None
    _premium: float = None
    
    # Get Hex and Decimal ID
    def __post_init__(self):
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

    def decid(self):
        hasher = keccak.new(digest_bits=256)
        hasher.update(self.name.encode('utf-8'))
        hex = hasher.hexdigest()
        return int(hex, 16)

    # Get line string for csv output
    def getcsv(self):
        url = f"https://opensea.io/assets/0x57f1887a8bf19b14fc0df6fd9b2acc9af147ea85/{self.decid()}" if self._enstype is ENSType.OWNED else f"https://app.ens.domains/name/{self.name}.eth/register"
        attrs = [self.name,
                 self.owner,
                 len(self.name),
                 self._enstype.value,
                 self._premium,
                 url,
                 self.creationdate,
                 self.registrationdate,
                 self.expirydate,
                 self._gracedate,
                 self._premiumdate]
        return ",".join([str(i) if i else '' for i in attrs])

# Get a list of all of the valid words.
def getwords(dirname: str):
    with open(dirname, encoding='utf-8') as txtfile:
        lines = txtfile.readlines()
    print(f"\nBulk searching {len(lines)} words in {dirname}...")
    words = [line[:-1] if '\n' in line else line for line in lines]
    validwords = [name for name in words if len(name) > 2 and re.search(r'[\[\] \.\_\+\\]', name) is None]
    return validwords, len(words)-len(validwords)

# Get the data for each domain
def getlistingdata(words: list[str]):
    rate = 100 #50 if max([len(i) for i in words]) > 256 else 5000
    chunks = [words[i:i+rate] for i in range(0, len(words), rate)]
    rjsons = [{"query": QUERY,
             "variables": {
                "labelName_in": chunk
            }} for chunk in chunks]
    with requests.Session() as s:
        retries = Retry(total=5, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504], raise_on_redirect=True,
                        raise_on_status=True)
        s.mount('http://', HTTPAdapter(max_retries=retries))
        s.mount('https://', HTTPAdapter(max_retries=retries))
        reqs = (grequests.post(url=URL, json=rjson, session=s) for rjson in rjsons)
        responses = grequests.map(reqs)
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
        owner = entry["domain"]["owner"]["id"]
        createddt = datetime.datetime.fromtimestamp(float(entry["domain"]["createdAt"]))
        expirydt = datetime.datetime.fromtimestamp(float(entry["expiryDate"]))
        registrationdt = datetime.datetime.fromtimestamp(float(entry["registrationDate"]))
        return ENSListing(name, owner, createddt, expirydt, registrationdt)
    domains += [generateenslisting(entry) for entry in domaindata]
    return sortdomains(words, domains)

# region saving

def makeoutputdir(dirname: str):
    outputdir = dirname.removesuffix(".txt").replace("input", "output", 1)
    os.makedirs(outputdir, exist_ok=True)
    os.chdir(outputdir)
    # if not os.path.exists("./output"): os.mkdir("./output")
    # if os.path.exists(f"./output/{dirname}"): shutil.rmtree(f"./output/{dirname}")
    # os.mkdir(f"./output/{dirname}")
    # os.chdir(f'./output/{dirname}')

# Saves a text file with all the non-premium words
def saveavailable(domains: list[ENSListing]):
    enslist = [i.name for i in domains if i._enstype in [ENSType.NEW, ENSType.EXPIRED]]
    if not enslist: return
    with open(f"available.txt", 'w', encoding='utf-8') as file:
        file.write("\n".join(enslist))

# Saves valid words and words seperated by length
def savevalid(words: list[str]):
    with open(f"valid.txt", 'w', encoding='utf-8') as file:
        file.write("\n".join(words))

def savelength(words: list[str]):
    lengthdict = defaultdict(list)
    for word in words: lengthdict[len(word)].append(word)
    if not (len(words)*0.5 > len(lengthdict) > 1): return
    os.makedirs(os.path.join(os.getcwd(), "length"), exist_ok=True)
    for i, iwords in lengthdict.items():
        with open(f"./length/{i} chars.txt", 'w', encoding='utf-8') as file:
            file.write("\n".join(iwords))

# Saves a CSV containing data for all of the domains provided
def savedomains(domains: list[ENSListing]):
    enslist = ["Name,Current Owner,Length,Status,Premium,URL,Created,Registered,Expires,Grace Period Ends,Price Premium Ends"]
    enslist += [i.getcsv() for i in domains]
    with open(f"domains.csv", 'w', encoding='utf-8') as file:
        file.write("\n".join(enslist))

# Saves a CSV containing data for all of the domains provided
def savewhales(domains: list[ENSListing]):
    owners = defaultdict(int)
    for domain in domains:
        owners[domain.owner] += 1
    if None in owners.keys(): owners.pop(None)
    items = [[name, num] for name, num in owners.items()]
    items.sort(key=lambda x: x[1], reverse=True)
    enslist = ["Number Held,Address,Opensea"]
    enslist += [f"{num},{owner},https://opensea.io/{owner}" for owner, num in items]
    with open(f"whales.csv", 'w', encoding='utf-8') as file:
        file.write("\n".join(enslist))

# Update readme and print summary
def readmeandprint(start: datetime.datetime,
                   words: list[str],
                   numinvalid: int,
                   domainobjs: list[ENSListing],
                   update = False,
                   readmepath = ""):
    numvalid = len(words)
    numavailable = len([i.name for i in domainobjs if i._enstype is ENSType.NEW or i._enstype is ENSType.EXPIRED])
    numpremium = len([d for d in domainobjs if d._enstype is ENSType.PREMIUM])
    pastday = len(['' for i in domainobjs if i.registrationdate and i.registrationdate > (datetime.datetime.now()-datetime.timedelta(days=1))])
    elapsed = (datetime.datetime.now() - start).total_seconds()
    totalwords = numvalid+numinvalid
    if update: updatereadme(numavailable, pastday, readmepath)
    printstr = (f"ENS bulk search completed in {elapsed:.2f} seconds.\n"
                f"{totalwords} Words Searched\n"
                f"{numvalid} Valid ({(numvalid*100.0)/totalwords:.2f}%)\n"
                f"{numinvalid} Invalid ({(numinvalid*100.0)/totalwords:.2f}%)\n")
    if numavailable: printstr += f"{numavailable} Available for base price ({(numavailable*100.0)/numvalid:.2f}%)\n"
    if numpremium: printstr += f"{numpremium} Available for premium price ({(numpremium*100.0)/numvalid:.2f}%)\n"
    if numavailable: printstr += f"{pastday} Registered in the past day ({(pastday*100.0)/(numavailable+pastday):.2f}%)\n"
    print(printstr)
    return pastday

# Autoupdate readme with new statistics (can be disabled)
def updatereadme(numavailable: int, pastday: int, readmepath: str):
    with open(readmepath, 'r', encoding='utf-16') as readme:
        rmstr = readme.read()
        rmstr = re.sub(r"As of last update, \d+ words are available, with \d+ sales in the past day",
                       f"As of last update, {numavailable} words are available, with {pastday} sales in the past day",
                       rmstr)
    with open(readmepath, 'w', encoding='utf-16') as readme:
        readme.write(rmstr)

# endregion

def main():
    # Getting data
    total = 0
    readmepath = os.path.join(os.getcwd(), "README.md")
    for filename in glob(os.path.join(os.getcwd(), "input/**/*.txt"), recursive=True):
        start = datetime.datetime.now()
        words, numinvalid = getwords(filename)
        domaindata = getlistingdata(words)
        domainobjs = getdomains(words, domaindata)
        # Outputs
        makeoutputdir(filename)
        if config.AVAILABLE: saveavailable(domainobjs)
        if config.VALID and numinvalid: savevalid(words)
        if config.LENGTH: savelength(words)
        if config.DOMAINS: savedomains(domainobjs)
        if config.WHALES: savewhales(domainobjs)
        update = config.README and '20kWordClub' in filename
        total += readmeandprint(start, words, numinvalid, domainobjs, update, readmepath)
    print(f"Total of {total} ENS registered in the past day in all searched files.\n")

if __name__ == '__main__':
    main()