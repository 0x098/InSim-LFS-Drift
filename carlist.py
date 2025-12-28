_cars = "UF1,XFG,XRG,LX4,LX6,RB4,FXO,XRT,RAC,FZ5,UFR,XFR,FXR,XRR,FZR,MRT,FBM,FOX,FO8,BF1"
VALID = {}
for cr in _cars.split(","):
  VALID[cr[::-1].encode('ascii').hex().upper()] = cr
