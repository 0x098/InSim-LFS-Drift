# InSim-LFS-Drift
InSim PY Script to track Drift Score in LFS (Runtime only. Saving to DB is unfinished atm)

open folder in cmd and just py/python3 insim.py

all user-end-point config stuff is in insimconfig.py

## 09.07.25
added penalty system to reduce or add points depending on object id and if its static or not.
current config modifies scores as:

green cones and poles add about 100

bale reduces by 100

all other objects also 100

1.5x of this value if its a static object

whenever hitting an object the score goes red (addition < 0 ) or green (addition > 0)

angle color now works along with config / speed left untouched currently

micro optimizations

![ingame look](https://github.com/0x098/InSim-LFS-Drift/blob/main/img/ingame.png)

feel free to pr i guess
