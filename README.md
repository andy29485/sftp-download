# SFTP Downloader

A simple ~~personal~~ sftp file downloader for episodes, with emby integration.

## Installation

#### Linux
- Install python3.6 or greater using a your package manager:
  `sudo apt install python3.6 pip3` or `sudo pacman -S python python-pip`
- Then install the requirements
```
sudo pip3 install -U -r requirements.txt
```

#### Windows
- Install [python3.6 or newer](https://www.python.org/downloads/)
  - Make sure that python is in your path
- Then install the requirements
  - (use a command line shell, like git bash or cmd)
```
python -m pip install -U -r requirements.txt
```

## Configuring


## Bash Completion
- Set up bash completion for your local user
```bash
mkdir -p ~/.bash_completion.d/
printf "for bc in ~/.bash_completion.d/*;do\n  . \"$bc\"\ndone\n" > ~/.bash_completion
```
- copy the `sftp_downloader_py` file to your `~/.bash_completion.d/` dir
- add the current dir to your path variable:
  - append the following to your `~/.bashrc` file:
    ```PATH="$PATH:<PATH TO sftp-downloader.py DIR>"```
