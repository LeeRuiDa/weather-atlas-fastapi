from numbers import Real
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings
from app.errors import UpstreamDataError, UpstreamServiceError, UpstreamTimeoutError
from app.schemas import NearbyPlaceResponse


class WikimediaClient:
    provider_name = "Wikimedia"

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    async def nearby_places(
        self, latitude: float, longitude: float, radius_m: int, limit: int
    ) -> list[NearbyPlaceResponse]:
        params = {
            "action": "query",
            "format": "json",
            "list": "geosearch",
            "gscoord": f"{latitude}|{longitude}",
            "gsradius": radius_m,
            "gslimit": limit,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.external_api_timeout_seconds,
                headers={"User-Agent": self.settings.wikimedia_user_agent},
                transport=self.transport,
            ) as client:
                response = await client.get(self.settings.wikimedia_api_url, params=params)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise UpstreamTimeoutError(self.provider_name) from exc
        except httpx.HTTPStatusError as exc:
            raise UpstreamServiceError(
                self.provider_name, exc.response.status_code
            ) from exc
        except httpx.RequestError as exc:
            raise UpstreamServiceError(self.provider_name) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamDataError(self.provider_name) from exc
        if not isinstance(payload, dict):
            raise UpstreamDataError(self.provider_name)
        query = payload.get("query")
        places = query.get("geosearch") if isinstance(query, dict) else None
        if not isinstance(places, list):
            raise UpstreamDataError(self.provider_name)
        return [self._parse_place(place) for place in places]

    def _parse_place(self, place: Any) -> NearbyPlaceResponse:
        if not isinstance(place, dict):
            raise UpstreamDataError(self.provider_name)
        page_id = place.get("pageid")
        title = place.get("title")
        latitude = place.get("lat")
        longitude = place.get("lon")
        distance = place.get("dist")
        numeric_values = (page_id, latitude, longitude, distance)
        if (
            not isinstance(page_id, int)
            or isinstance(page_id, bool)
            or not isinstance(title, str)
            or any(not isinstance(value, Real) or isinstance(value, bool) for value in numeric_values[1:])
        ):
            raise UpstreamDataError(self.provider_name)
        slug = quote(title.replace(" ", "_"), safe="")
        return NearbyPlaceResponse(
            page_id=page_id,
            title=title,
            latitude=float(latitude),
            longitude=float(longitude),
            distance_m=float(distance),
            article_url=f"https://en.wikipedia.org/wiki/{slug}",
        )
