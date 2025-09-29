#!/usr/bin/env python3
"""Fetch prefab home builder listings in Texas from Google Maps Places API.

This script queries the Google Maps Places Text Search API for multiple search
terms related to prefab home builders in Texas and retrieves details for each
matching business. The aggregated results are exported to a CSV file with the
following columns:

    business name, Place ID, website URL, phone, full address,
    average rating, rating count

Usage:
    GOOGLE_MAPS_API_KEY=your_api_key python fetch_prefab_builders.py output.csv

The API key must be provided via the ``GOOGLE_MAPS_API_KEY`` environment
variable. The script deduplicates businesses across search terms by their
Place ID.
"""

from __future__ import annotations

import csv
import os
import sys
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set

import requests

TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

SEARCH_TERMS = [
    "prefab home builder",
    "modular home builder",
    "manufactured home builder",
]

DETAIL_FIELDS = (
    "name,place_id,website,formatted_phone_number,"
    "formatted_address,rating,user_ratings_total"
)

REQUEST_TIMEOUT = 30  # seconds
NEXT_PAGE_DELAY = 2.5  # seconds; Google recommends waiting a couple seconds


@dataclass
class Place:
    name: str
    place_id: str
    website: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    rating: Optional[float]
    rating_count: Optional[int]

    @classmethod
    def from_details(cls, data: Dict[str, object]) -> "Place":
        return cls(
            name=str(data.get("name", "")),
            place_id=str(data.get("place_id", "")),
            website=data.get("website"),
            phone=data.get("formatted_phone_number"),
            address=data.get("formatted_address"),
            rating=(float(data["rating"]) if "rating" in data else None),
            rating_count=(
                int(data["user_ratings_total"])
                if "user_ratings_total" in data
                else None
            ),
        )


class GooglePlacesClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def text_search(self, query: str) -> Iterable[Dict[str, object]]:
        """Yield raw place entries returned for a text search query."""
        params = {
            "query": query,
            "region": "us",
            "key": self.api_key,
        }

        next_page_token: Optional[str] = None
        while True:
            if next_page_token:
                params["pagetoken"] = next_page_token
                # Google requires a short wait before using next_page_token
                time.sleep(NEXT_PAGE_DELAY)
            else:
                params.pop("pagetoken", None)

            response = requests.get(TEXT_SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            payload = response.json()

            status = payload.get("status")
            if status not in {"OK", "ZERO_RESULTS"}:
                error_message = payload.get("error_message", "")
                raise RuntimeError(
                    f"Text search request failed with status {status}: {error_message}"
                )

            results = payload.get("results", [])
            for result in results:
                yield result

            next_page_token = payload.get("next_page_token")
            if not next_page_token:
                break

    def fetch_place_details(self, place_id: str) -> Place:
        params = {
            "place_id": place_id,
            "fields": DETAIL_FIELDS,
            "key": self.api_key,
        }
        response = requests.get(PLACE_DETAILS_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()

        status = payload.get("status")
        if status != "OK":
            error_message = payload.get("error_message", "")
            raise RuntimeError(
                f"Place details request failed for {place_id} with status {status}: {error_message}"
            )

        result = payload.get("result", {})
        return Place.from_details(result)


def fetch_all_places(client: GooglePlacesClient) -> List[Place]:
    seen_place_ids: Set[str] = set()
    places: List[Place] = []

    for term in SEARCH_TERMS:
        query = f"{term} in Texas"
        for entry in client.text_search(query):
            place_id = entry.get("place_id")
            if not place_id or place_id in seen_place_ids:
                continue

            seen_place_ids.add(place_id)
            try:
                details = client.fetch_place_details(place_id)
            except Exception as exc:  # noqa: BLE001 - propagate useful context
                print(
                    f"Warning: failed to fetch details for place {place_id}: {exc}",
                    file=sys.stderr,
                )
                continue

            places.append(details)

    return places


def export_to_csv(places: Iterable[Place], output_path: str) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(
            [
                "business name",
                "Place ID",
                "website URL",
                "phone",
                "full address",
                "average rating",
                "rating count",
            ]
        )
        for place in places:
            writer.writerow(
                [
                    place.name,
                    place.place_id,
                    place.website or "",
                    place.phone or "",
                    place.address or "",
                    f"{place.rating:.1f}" if place.rating is not None else "",
                    place.rating_count if place.rating_count is not None else "",
                ]
            )


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print(
            "Usage: GOOGLE_MAPS_API_KEY=your_api_key python fetch_prefab_builders.py output.csv",
            file=sys.stderr,
        )
        return 1

    output_path = argv[1]
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("Error: GOOGLE_MAPS_API_KEY environment variable is not set", file=sys.stderr)
        return 1

    client = GooglePlacesClient(api_key)
    places = fetch_all_places(client)
    export_to_csv(places, output_path)
    print(f"Exported {len(places)} businesses to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
