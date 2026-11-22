"""Combat-first mechfight/1 bot. Stdout is the protocol; logs stay on stderr."""
import mechfight as mf
from combat.pilot import CombatBot

mf.run(CombatBot)
