# Hex(pansion) Manager app

EMF Camp Badge App for managing hexpansion. Supports initialising, erasing and upgrading them.  Provies means to serialise a batch with unique ids.  Additional hexpansion varieties can easily be added.  The ides is that anyone can use this app rather than each developer who makes a hexpansion with software having to write this capability from scratch.

## User guide

Install the HexManager app and then plug your hexpansion board into any of the hexpansion slots on your EMF Camp 2024/2026 Badge.  If your hexpansion EEPROM has not been initialised before you will be promted to confirm which type of hexpansion it is.

### Main Menu ###

The main menu presents the following options:
- **Hexpansions** – Live information on currently plugged in hexpansions
- **Serialise** – Initialise a batch of hexpansions, each with a unique_id for serialisation.
- **Settings** – Adjust configurable parameters (see below)
- **About** – Show version info, animated logo and QR code
- **Exit** – Exit the BadgeBot app

### Settings ###

The main menu includes a sub-menu of Settings which can be adjusted.
| Setting          | Description                               | Default        | Min    | Max    |
|------------------|-------------------------------------------|----------------|--------|--------|
| unique_id        | Starting ID for serialisation             | 1              | 1      | 65535  |
| logging          | Enable or disable logging                 | False          | False  | True   |

### Install guide

Stable version available via [Tildagon App Directory](https://apps.badge.emfcamp.org/).

### Hexpansion Recovery ###

If you have issues with any hexpansion fitted with an EEPROM, e.g. a software incompatibility with a particular badge software version, you can reset the EEPROM back to blank as follows:
1) Plug in the hexpansion to Slot 1 (will work with any slot but you have to change the "1" below to the slot number.
2) Connect your favourite Terminal program to the COM port presented by the Badge over USB.
3) Press "Ctrl" & "C" simultaneously. i.e. "Ctrl-C" 
4) You should now be presented with a prompt ">>>" which is called the python REPL. At this type in the following lines (the HexDrive EEPROM is 8kbytes so requires 16 bit addressing, hence the ```addrsize=16``` other hexpansions may use smaller EEPROMS where this is not required):
   ```
		from machine import I2C
		i = I2C(1)
		i.writeto_mem(0x50, 0, bytes([0xFF]*8192), addrsize=16)
   ```
6) As long as there is no Traceback then this worked. But you can check by reading back the EEPROM contents with:
   ```
		i.readfrom_mem(0x50,0,32,addrsize=16)
   ```
	You should get a response which confirms that the first 32 bytes have been reset back to 0xFF:
```
    b'\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff'
```


### Developers setup
This is to help develop the HexManager application using the Badge simulator.

Windows:
```
git clone https://github.com/TeamRobotmad/HexManager.git
cd HexManager
powershell -ExecutionPolicy Bypass -File .\dev\setup_dev_env.ps1
```

WSL (recommended for simulator tests):
```
git clone https://github.com/TeamRobotmad/HexManager.git
cd HexManager
sh ./dev/setup_wsl_dev_env.sh
```

The WSL helper uses `uv` to provision Python 3.10 and installs both the local dev requirements and the simulator requirements. This is recommended because the published `wasmer` wheels used by the simulator currently load reliably there.

Linux/macOS:
```
git clone https://github.com/TeamRobotmad/HexManager.git
cd HexManager
sh ./dev/setup_dev_env.sh
```

If you prefer to run commands manually:
```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r .\dev\dev_requirements.txt
```


### Running tests
Tests must be run from the `tests/` directory:
```
cd tests
python -m pytest test_smoke.py test_autotune.py -v
```

If HexManager is checked out inside the `badge-2024-software` repo, set `PYTHONPATH` to the parent repo root so `sim.run` can be imported. For the WSL helper's default environment this looks like:
```
cd tests
PYTHONPATH=/path/to/badge-2024-software ../.venv-wsl310/bin/python -m pytest test_smoke.py test_autotune.py -v
```

### Best practise
Run `isort` on in-app python files. Check `pylint` for linting errors.


### Contribution guidelines
