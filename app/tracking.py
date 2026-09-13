"""
Tracking endpoints:
  GET /track/open/{token}.png  -> logs an open, returns a 1x1 transparent gif
  GET /track/click/{token}     -> logs a click, redirects to the real URL
"""
from datetime import datetime
from fastapi import APIRouter, Depends, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Send, Open, Click

router = APIRouter(prefix="/track", tags=["tracking"])

# 1x1 transparent GIF bytes
PIXEL_GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
)


@router.get("/open/{token}.png")
def track_open(token: str, db: Session = Depends(get_db)):
    send = db.query(Send).filter(Send.tracking_token == token).first()
    if send:
        existing = db.query(Open).filter(Open.send_id == send.id).first()
        if existing:
            existing.open_count += 1
            existing.opened_at = datetime.utcnow()
        else:
            db.add(Open(send_id=send.id, opened_at=datetime.utcnow(), open_count=1))
        db.commit()
    return Response(content=PIXEL_GIF, media_type="image/gif")


@router.get("/click/{token}")
def track_click(token: str, url: str, db: Session = Depends(get_db)):
    send = db.query(Send).filter(Send.tracking_token == token).first()
    if send:
        db.add(Click(send_id=send.id, clicked_at=datetime.utcnow(), target_url=url))
        db.commit()
    return RedirectResponse(url)
