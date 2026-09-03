from __future__ import annotations

from twilio.rest import Client

from app.config import env


def maybe_call(message: str) -> bool:
    required = ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "MY_PHONE_NUMBER"]
    if any(not env(name) for name in required):
        return False
    client = Client(env("TWILIO_ACCOUNT_SID"), env("TWILIO_AUTH_TOKEN"))
    twiml = f"<Response><Say>{message}</Say></Response>"
    client.calls.create(to=env("MY_PHONE_NUMBER"), from_=env("TWILIO_FROM_NUMBER"), twiml=twiml)
    return True
