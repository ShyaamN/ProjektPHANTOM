"""ProjektPHANTOM mechfight/1 bot.

stdout is reserved for protocol messages. The official wrapper in mechfight.py
owns the stdin/stdout loop, tick echo, and newest-observation rule.
"""
import mechfight as mf
from strategy.brain import Brain


def main() -> None:
    mf.run(Brain)


if __name__ == "__main__":
    main()
