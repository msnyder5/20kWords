# 20k Words Club
Welcome to the github repository of the ENS 20k Words Club. There are a number of resources included for the 20k Words collection, as well as for general ENS bulk searching. You can join the 20k Words Club Discord here: https://discord.gg/nG5cyX4fw8

# available.txt
A text file containing all of the available domains. See `main.py` for updating this file.

# names.csv
A CSV containing data on all of the domains. Columns include, `Name`, `Length`, `Status`, `Premium`, and more. See `main.py` for updating this file.

# n letters.txt
Individual text files containing all of the words of the given length. See `main.py` for updating this file.

# main.py
Python script for bulk searching ENS domains.

## Setup
Run `pip install -r requirements.txt` or `pip install grequests pycryptodome` to install the rquired python libraries.

## Customization
### Custom Domain Lists
You can use the script on any text file with names seperated by newlines. Simply change the value of `INPUT` on line 9 to point to the desired text file.

### Custom File Names
It is possible to set custom file names to analyze multiple word lists without overwriting files. Change the file name variables on lines 10-13 to change the file names.

Note 1: File folder and extension are handled for you, just input the name like `'validwords'`.

Note 2: For `LETTERS` you must keep one set of `{}` in the string where the word length will be inserted.