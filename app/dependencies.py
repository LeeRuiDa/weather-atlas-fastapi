from fastapi import Request

from app.services.open_meteo import OpenMeteoClient
from app.services.wikimedia import WikimediaClient


def get_open_meteo_client(request: Request) -> OpenMeteoClient:
    return request.app.state.open_meteo_client


def get_wikimedia_client(request: Request) -> WikimediaClient:
    return request.app.state.wikimedia_client

