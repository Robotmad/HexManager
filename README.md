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



### Construction guide & useful documents

https://github.com/TeamRobotmad/BadgeBotParts/tree/main/Docs


## Developers guide

Writing your own code to control the motor driver is very easy.  The BadgeBot application contains lots of extra code to support initialising and upgrading the software on the HexDrive, but once this is done you can use the board without needing this code.

To fit the HexDrive software into a small EEPROM it is converted into a .mpy file.  The file hexdrive.py is the source of this code if you want to see what it is doing.  The intention is that this code manages the hardware as it knows which slot the hexpansion is in.

### Power
The HexDrive incorporates a Switch Mode Power Supply which boosts the 3.3V provided by the badge up to 5V (or higher if your hexpansion has been modified) to drive the motors.  To turn this on or off call
```set_power(True | False)```

### Drive
Call ```set_motors()``` to control the two motors, providing a signed integer from -65535 to +65535 for each in a tuple.

Alternatively:
Call ```set_pwm()``` to set the duty cycle of the 4 PWM channels which control the motors. This function takes a tuple of 4 integers, each from 0 to 65535. e.g.
```set_pwm((0,1000,1000,0))```
note the extra set of brackets as the function argument is a single tuple of 4 values rather than being 4 individual values.

### Servos
You can control 1,2,3 or 4 RC hobby servos (centre pulse width 1500us).  The first time you set a pulse width for a channel using ```set_servoposition()``` the PWM frequency for that channel will be set to 50Hz.
The first two Channels take up signals that would otherwise control Motor 1 and the second two Channels take up the signals that are used for Motor 2.
You can use one motor and 1 or 2 servos simultaneously.

### Frequency
You can adjust the PWM frequency, default 20000Hz for motors and 50Hz for servos by calling the ```set_freq()``` function.

#### Keep Alive
To protect against most badge/software crashes causing the motors or servos to run out of control there is a keep alive mechanism which means that if you do not make a call to the ```set_pwm```, ```set_motors``` or ```set_servoposition``` functions the motors/servos will be turned off after 1000mS (default - which can be changed with a call to ```set_keep_alive()```).

### Developers setup
This is to help develop the BadgeBot application using the Badge simulator.

Windows:
```
git clone https://github.com/TeamRobotmad/BadgeBot.git
cd BadgeBot
powershell -ExecutionPolicy Bypass -File .\dev\setup_dev_env.ps1
```

WSL (recommended for simulator tests):
```
git clone https://github.com/TeamRobotmad/BadgeBot.git
cd BadgeBot
sh ./dev/setup_wsl_dev_env.sh
```

The WSL helper uses `uv` to provision Python 3.10 and installs both the local dev requirements and the simulator requirements. This is recommended because the published `wasmer` wheels used by the simulator currently load reliably there.

Linux/macOS:
```
git clone https://github.com/TeamRobotmad/BadgeBot.git
cd BadgeBot
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

If BadgeBot is checked out inside the `badge-2024-software` repo, set `PYTHONPATH` to the parent repo root so `sim.run` can be imported. For the WSL helper's default environment this looks like:
```
cd tests
PYTHONPATH=/path/to/badge-2024-software ../.venv-wsl310/bin/python -m pytest test_smoke.py test_autotune.py -v
```

### Best practise
Run `isort` on in-app python files. Check `pylint` for linting errors.

### Regenerating QR Code
QR generation is a development-time task and is intentionally kept out of normal
runtime loading for the app.

Generate QR output only (prints `_QR_CODE = [...]`):
```
python dev/generate_qr_code.py --url https://robotmad.odoo.com
```

Generate and write directly back into `app.py`:
```
python dev/generate_qr_code.py --url https://robotmad.odoo.com --write-app
```

Optional: integrate into release prep:
```
python dev/build_release.py --refresh-qr --qr-url=https://robotmad.odoo.com
```

Validate `_QR_CODE` is in sync without modifying files:
```
python dev/check_qr_sync.py --url https://robotmad.odoo.com
```

`build_release.py` now checks QR sync by default before packaging.
Use `--no-check-qr` to skip this check if needed.


### Contribution guidelines
