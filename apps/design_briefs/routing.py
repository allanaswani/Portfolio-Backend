"""Which MCS team lead receives a brief, and who is copied.

Straight from MCS's "Decide Clearly so that we can Execute Fast" notice
(Nov 2026), "all design, video, event, marketing & internal communications
briefs will be received like so":

    Banking & Insurance      send to Achieng Oluoch   copy Graca Owuor
    Properties               send to Nyambura Mburu   copy Brian Angiro
    Internal Communications  send to Achieng Oluoch   copy Dorine Karanja

Escalations go to the MCS Helpdesk, marketinghelpdesk@hfcb.co.ke.

Every address can be overridden from the environment without a deploy
(MCS_ROUTE_<AREA>_TO / _CC, MCS_HELPDESK_EMAIL), because who leads a desk
changes more often than the code does.
"""
import os

HELPDESK_DEFAULT = "marketinghelpdesk@hfcb.co.ke"

ROUTES = {
    "banking_insurance": ("Achieng.Oluoch@hfcb.co.ke", "Graca.Owuor@hfcb.co.ke"),
    "properties": ("Nyambura.Mburu@hfcb.co.ke", "Brian.Angiro@hfcb.co.ke"),
    "internal_comms": ("Achieng.Oluoch@hfcb.co.ke", "Dorine.Karanja@hfcb.co.ke"),
}


def _env(name, default):
    value = (os.environ.get(name) or "").strip()
    return value or default


def helpdesk():
    return _env("MCS_HELPDESK_EMAIL", HELPDESK_DEFAULT)


def route(area):
    """(lead address, copy address) for a business area, or ("", "")."""
    to, cc = ROUTES.get(area or "", ("", ""))
    key = (area or "").upper()
    return (_env(f"MCS_ROUTE_{key}_TO", to), _env(f"MCS_ROUTE_{key}_CC", cc))


def lead_name(area):
    """The lead's name for the form ("Goes to Achieng Oluoch")."""
    to, _cc = route(area)
    return _name(to)


def copy_name(area):
    _to, cc = route(area)
    return _name(cc)


def _name(address):
    local = (address or "").split("@")[0]
    return " ".join(p.capitalize() for p in local.replace("_", ".").split(".") if p)


def routes_for_ui():
    """Every area with who it goes to - the form shows it as you pick."""
    from .models import DesignBrief

    return [{"value": v, "label": l, "to": lead_name(v), "copy": copy_name(v)}
            for v, l in DesignBrief.AREAS]
