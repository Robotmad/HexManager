# Hex(pansion) Manager app

EMF Camp Badge App for managing hexpansion. Supports initialising, erasing and upgrading them.  Provies means to serialise a batch with unique ids.  Additional hexpansion varieties can easily be added.  The ides is that anyone can use this app rather than each developer who makes a hexpansion with software having to write this capability from scratch.

## User guide

Install the HexManager app and then plug your hexpansion board into any of the hexpansion slots on your EMF Camp 2024/2026 Badge.  If your hexpansion EEPROM has not been initialised before you will be promted to confirm which type of hexpansion it is.

### Main Menu ###

The main menu presents the following options:
- **Hexpansions** – Live information on currently plugged in hexpansions
- **Serialise** – Initialise a batch of hexpansions, each with a unique_id for serialisation.
- **Settings** – Adjust configurable parameters (see below)
- **About** – Show version info and a count of the number of hexpansion types known to the app
- **Exit** – Exit the BadgeBot app

### Settings ###

The main menu includes a sub-menu of Settings which can be adjusted.
| Setting          | Description                               | Default        | Min    | Max    |
|------------------|-------------------------------------------|----------------|--------|--------|
| unique_id        | Starting ID for serialisation             | 1              | 1      | 65535  |
| logging          | Enable or disable logging                 | False          | False  | True   |

### Adding Your Own Hexpansion ###

HexManager reads hexpansion type definitions from a JSON file named **`hexpansions.json`** that lives in the HexManager app folder on the badge (e.g. `/apps/HexManager/hexpansions.json`).  This file ships with entries for all the built-in hexpansion types and is designed to be easy to extend.

#### Steps to add a new hexpansion type

1. **Copy `hexpansions.json`** from this repository to your computer and open it in any text editor.

2. **Add a new entry** to the `"hexpansions"` list.  You only need `pid` and `name` at minimum:

   ```json
   {
     "pid": 4096,
     "name": "MyHexpansion",
     "vid": 51966,
     "sub_type": "Rev A",
     "eeprom_total_size": 8192,
     "eeprom_page_size": 32,
     "app_mpy_name": "myhex.mpy",
     "app_mpy_version": 1,
     "app_name": "MyHexApp"
   }
   ```

   > **Important:** all integer values in JSON are **decimal** (not hex).  Use a calculator to convert:  
   > `0xCAFE = 51966`,  `0xCBCB = 52171`,  `0x1000 = 4096`, etc.

3. **Field reference** – see the `"_help"` section inside `hexpansions.json` for a full description of every field.  A summary:

   | Field | Required | Default | Description |
   |---|---|---|---|
   | `pid` | ✅ | – | Product ID (0–65535). Must be unique within the same VID. |
   | `name` | ✅ | – | Display name shown on screen (keep ≤ 12 chars). |
   | `vid` | No | 51966 (0xCAFE) | Vendor ID.  TeamRobotmad uses 52171 (0xCBCB). |
   | `eeprom_total_size` | No | 8192 | EEPROM size in **bytes** (e.g. 2048, 8192, 32768, 65536). |
   | `eeprom_page_size` | No | 32 | Write page size in **bytes** – check your EEPROM datasheet (e.g. 16, 32, 64, 128). |
   | `sub_type` | No | – | Short label for a specific variant, e.g. `"2 Motor"`. |
   | `app_mpy_name` | No | – | Filename of the compiled `.mpy` app to flash to the EEPROM. |
   | `app_mpy_version` | No | – | Integer version of the `.mpy` app (used to detect when an upgrade is needed). |
   | `app_name` | No | – | Python class name of the hexpansion app, used to check if it is already running. |

4. **Prepare the app `.mpy` file** *(only needed if your hexpansion has its own badge app)*:

   > **⚠️ Current limitation:** the app written to the EEPROM must be a **single `.mpy` file**.  Support for copying multiple files will be added in a future release.

   - Write your hexpansion badge app in Python (e.g. `myhex.py`).
   - Compile it to an `.mpy` bytecode file using the **`mpy-cross`** utility (part of MicroPython):
     ```bash
     pip install mpy-cross
     mpy-cross myhex.py         # produces myhex.mpy
     ```
   - **The `.mpy` file must be placed in the HexManager app folder on the badge** (same folder as `app.mpy` / `hexpansion_mgr.mpy`, typically `/apps/HexManager/`).  Upload it via the badge's USB file system, `mpremote`, or any other method you prefer.

5. **Upload `hexpansions.json`** to the badge, replacing the existing file at `/apps/HexManager/hexpansions.json`.

6. **Restart the badge app** – HexManager will load the updated file on next launch.  
   If the file is missing or contains a JSON error, a warning message will be shown on screen and printed to the serial console.

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
5) As long as there is no Traceback then this worked. But you can check by reading back the EEPROM contents with:
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
