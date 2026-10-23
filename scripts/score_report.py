"""Print the scorebook for calibration and review. Usage: python -m scripts.score_report"""

from app.config import get_settings, load_scoring_config
from app.data.db import connect, load_daily, load_nri
from app.domain.hubs import HubRegistry
from app.domain.scoring import build_scorebook


def main() -> None:
    settings, cfg = get_settings(), load_scoring_config()
    conn = connect(settings.db_path)
    hubs = HubRegistry.from_json(settings.hubs_path).all()
    book = build_scorebook(hubs, load_daily(conn), load_nri(conn), cfg)
    names = list(cfg.hazards)
    print(f"scoring v{book.version}")
    print(f"{'#':>2} {'hub':<13}{'R':>6} {'label':<7}" + "".join(f"{n[:8]:>9}" for n in names))
    for h in book.ranked():
        cells = "".join(f"{h.hazards[n].score:9.1f}" for n in names)
        print(f"{h.rank:>2} {h.hub_id:<13}{h.composite:6.1f} {h.label:<7}{cells}")
    print("\nobserved rates (days/yr) and OBS vs NRI:")
    for h in book.ranked():
        parts = [
            f"{n}: obs={hs.obs:.0f} nri={hs.nri:.0f} {hs.obs_metrics}"
            for n, hs in h.hazards.items()
            if hs.obs is not None
        ]
        print(f"{h.hub_id:<13} flags={h.flags}\n    " + "\n    ".join(parts))


if __name__ == "__main__":
    main()
