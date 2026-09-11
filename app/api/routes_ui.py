"""The Today screen, served from the API that feeds it.

Plan §10.3's Glacier reference (`docs/ui/glacier-today.html`) was built as a
static file so the design could be looked at rather than described. This
serves that same file from the backend, so the four designed mornings and the
real one can be flipped between side by side.

The page is unauthenticated because it is markup. Everything it displays comes
from `/api/v1/today`, which is not: the browser supplies the bearer token, and
an unauthenticated visitor sees an empty screen rather than data.

This is deliberately not the Expo app. Plan §4.2 and D5 still stand — one
React Native codebase, which is also the only clean way to read Health Connect
in Phase 3. This is the MVP that makes the design touchable now, against real
data, without building the frontend twice.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(tags=["ui"])

UI_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "ui"
UI_FILE = UI_DIR / "glacier-today.html"
CHECKIN_FILE = UI_DIR / "glacier-checkin.html"


def _page(path: Path) -> FileResponse:
    if not path.exists():  # pragma: no cover - only if the repo is incomplete
        raise HTTPException(status_code=404, detail="UI reference file not found")
    # no-store: the file is edited by hand during design work, and a cached
    # copy of yesterday's layout is a confusing thing to debug.
    return FileResponse(path, media_type="text/html", headers={"Cache-Control": "no-store"})


@router.get("/ui", include_in_schema=False)
def today_screen() -> FileResponse:
    """The Today screen. Served from source so editing it needs no build step."""
    return _page(UI_FILE)


@router.get("/ui/checkin", include_in_schema=False)
def checkin_form() -> FileResponse:
    """The morning check-in.

    The subjective field this collects is the one that carries readiness over
    its 60% completeness floor: Samsung supplies four of the seven expected
    fields, which is 57.1%. Every other integration in the plan is worth less
    to the score than one tap here, which is why the page is built for speed
    before anything else.
    """
    return _page(CHECKIN_FILE)
