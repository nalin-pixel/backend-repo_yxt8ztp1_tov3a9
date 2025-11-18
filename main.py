import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson.objectid import ObjectId

from database import db, create_document, get_documents
from schemas import Area, PropertyListing, PropertyFAQ

app = FastAPI(title="Dubai Property Listings API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------
# Helpers
# -----------------------------

def _serialize(doc):
    if not doc:
        return doc
    doc = dict(doc)
    _id = doc.get("_id")
    if isinstance(_id, ObjectId):
        doc["id"] = str(_id)
        del doc["_id"]
    return doc


def _collection(name: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    return db[name]


# -----------------------------
# Health & test
# -----------------------------
@app.get("/")
def read_root():
    return {"message": "Dubai Property Listings Backend Running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"

    return response


# -----------------------------
# Areas (communities)
# -----------------------------
@app.post("/api/areas", response_model=dict)
def create_area(area: Area):
    collection = _collection("area")
    existing = collection.find_one({"slug": area.slug})
    if existing:
        raise HTTPException(status_code=400, detail="Area with this slug already exists")
    new_id = create_document("area", area)
    created = collection.find_one({"_id": ObjectId(new_id)})
    return _serialize(created)


@app.get("/api/areas", response_model=List[dict])
def list_areas(q: Optional[str] = Query(None, description="Search by name contains")):
    collection = _collection("area")
    filter_q = {}
    if q:
        filter_q = {"name": {"$regex": q, "$options": "i"}}
    docs = collection.find(filter_q).limit(100)
    return [_serialize(d) for d in docs]


@app.get("/api/areas/{slug}", response_model=dict)
def get_area(slug: str):
    collection = _collection("area")
    doc = collection.find_one({"slug": slug})
    if not doc:
        raise HTTPException(status_code=404, detail="Area not found")
    return _serialize(doc)


# -----------------------------
# Listings
# -----------------------------
@app.post("/api/listings", response_model=dict)
def create_listing(payload: PropertyListing):
    collection = _collection("propertylisting")
    exists = collection.find_one({"slug": payload.slug})
    if exists:
        raise HTTPException(status_code=400, detail="Listing with this slug already exists")
    new_id = create_document("propertylisting", payload)
    created = collection.find_one({"_id": ObjectId(new_id)})
    return _serialize(created)


class ListingsResponse(BaseModel):
    items: List[dict]
    total: int
    page: int
    page_size: int


@app.get("/api/listings", response_model=ListingsResponse)
def list_listings(
    q: Optional[str] = Query(None, description="Search in title and description"),
    transaction_type: Optional[str] = Query(None),
    property_type: Optional[str] = Query(None),
    area: Optional[str] = Query(None),
    area_slug: Optional[str] = Query(None),
    min_price: Optional[int] = Query(None, ge=0),
    max_price: Optional[int] = Query(None, ge=0),
    min_bed: Optional[float] = Query(None, ge=0),
    max_bed: Optional[float] = Query(None, ge=0),
    sort: Optional[str] = Query("newest", description="newest|price_asc|price_desc|size_desc|size_asc|psf_desc|psf_asc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=60),
):
    collection = _collection("propertylisting")
    f = {}
    if transaction_type:
        f["transaction_type"] = transaction_type
    if property_type:
        f["property_type"] = property_type
    if area:
        f["area"] = area
    if area_slug:
        f["area_slug"] = area_slug
    if min_price is not None or max_price is not None:
        price = {}
        if min_price is not None:
            price["$gte"] = min_price
        if max_price is not None:
            price["$lte"] = max_price
        f["price_aed"] = price
    if min_bed is not None or max_bed is not None:
        bed = {}
        if min_bed is not None:
            bed["$gte"] = min_bed
        if max_bed is not None:
            bed["$lte"] = max_bed
        f["bedrooms"] = bed
    if q:
        f["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"description_html": {"$regex": q, "$options": "i"}},
            {"highlights": {"$elemMatch": {"$regex": q, "$options": "i"}}},
        ]

    sort_map = {
        "newest": ("created_at", -1),
        "price_asc": ("price_aed", 1),
        "price_desc": ("price_aed", -1),
        "size_desc": ("bua_sqft", -1),
        "size_asc": ("bua_sqft", 1),
    }
    s_key, s_dir = sort_map.get(sort, ("created_at", -1))

    total = collection.count_documents(f)
    cursor = (
        collection.find(f)
        .sort(s_key, s_dir)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )

    items = [_serialize(d) for d in cursor]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.get("/api/listings/{slug}", response_model=dict)
def get_listing(slug: str):
    collection = _collection("propertylisting")
    doc = collection.find_one({"slug": slug})
    if not doc:
        raise HTTPException(status_code=404, detail="Listing not found")
    return _serialize(doc)


# -----------------------------
# FAQ for a listing
# -----------------------------
@app.post("/api/listings/{slug}/faq", response_model=dict)
def set_listing_faq(slug: str, payload: PropertyFAQ):
    collection = _collection("propertyfaq")
    listing_col = _collection("propertylisting")
    listing = listing_col.find_one({"slug": slug})
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    existing = collection.find_one({"listing_slug": slug})
    if existing:
        collection.update_one({"_id": existing["_id"]}, {"$set": payload.model_dump()})
        updated = collection.find_one({"_id": existing["_id"]})
        return _serialize(updated)
    new_id = create_document("propertyfaq", payload)
    created = collection.find_one({"_id": ObjectId(new_id)})
    return _serialize(created)


@app.get("/api/listings/{slug}/faq", response_model=dict)
def get_listing_faq(slug: str):
    collection = _collection("propertyfaq")
    doc = collection.find_one({"listing_slug": slug})
    if not doc:
        return {"listing_slug": slug, "faqs": []}
    return _serialize(doc)


# -----------------------------
# JSON-LD for SEO
# -----------------------------
@app.get("/api/listings/{slug}/jsonld", response_model=dict)
def listing_jsonld(slug: str):
    collection = _collection("propertylisting")
    listing = collection.find_one({"slug": slug})
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    listing = _serialize(listing)

    unit_type = "Apartment" if listing.get("property_type") == "Apartment" else "SingleFamilyResidence"
    jsonld = {
        "@context": "https://schema.org",
        "@type": "RealEstateListing",
        "name": listing.get("title"),
        "url": listing.get("canonical_url"),
        "datePosted": listing.get("created_at"),
        "description": listing.get("seo_description") or "",
        "item": {
            "@type": unit_type,
            "name": listing.get("title"),
            "numberOfRoomsTotal": listing.get("bedrooms"),
            "numberOfBathroomsTotal": listing.get("bathrooms"),
            "floorSize": {
                "@type": "QuantitativeValue",
                "value": listing.get("bua_sqft"),
                "unitCode": "FTK"
            },
            "address": {
                "@type": "PostalAddress",
                "addressLocality": listing.get("area"),
                "addressRegion": listing.get("emirate"),
                "addressCountry": "AE"
            }
        },
        "offers": {
            "@type": "Offer",
            "price": listing.get("price_aed"),
            "priceCurrency": "AED",
            "availability": "https://schema.org/InStock" if listing.get("status") == "Available" else "https://schema.org/OutOfStock"
        }
    }
    return jsonld


# -----------------------------
# Seed demo data (for preview)
# -----------------------------
@app.post("/api/seed")
def seed_demo():
    areas = _collection("area")
    listings = _collection("propertylisting")

    if not areas.find_one({"slug": "al-furjan"}):
        create_document(
            "area",
            Area(
                name="Al Furjan",
                emirate="Dubai",
                slug="al-furjan",
                intro="An established residential community with excellent connectivity and growing amenities.",
                avg_psf=1200.0,
                avg_price_1br=750000,
                avg_price_2br=1100000,
                avg_price_3br=1500000,
                rental_yield_pct=6.5,
                latitude=25.0402,
                longitude=55.1234,
                tags=["metro nearby", "family-friendly", "investor hotspot"],
            ),
        )

    if not listings.find_one({"slug": "2br-apartment-avenue-residence-4-al-furjan-dubai-12345"}):
        create_document(
            "propertylisting",
            PropertyListing(
                listing_id="AR4-2BR-12345",
                status="Available",
                transaction_type="Sale",
                property_type="Apartment",
                bedrooms=2,
                bathrooms=2,
                bua_sqft=1100,
                price_aed=1350000,
                service_charges_aed_psf=14.5,
                emirate="Dubai",
                area="Al Furjan",
                building="Avenue Residence 4",
                area_slug="al-furjan",
                title="2BR Apartment in Al Furjan – Close to Metro",
                slug="2br-apartment-avenue-residence-4-al-furjan-dubai-12345",
                seo_title="2BR Apartment for Sale in Avenue Residence 4, Al Furjan | AED 1.35M",
                seo_description="2 bedroom apartment for sale in Avenue Residence 4, Al Furjan – 1,100 sqft, close to metro, high rental demand.",
                canonical_url="/property/2br-apartment-avenue-residence-4-al-furjan-dubai-12345",
                description_html="<p>Bright and airy 2-bedroom apartment with modern finishing, steps from the Metro.</p>",
                highlights=["Near Metro", "Vacant on Transfer", "High ROI"],
                tags=["ready", "high roi"],
                main_image="https://images.unsplash.com/photo-1505693416388-ac5ce068fe85?q=80&w=1200&auto=format&fit=crop",
                gallery_images=[
                    "https://images.unsplash.com/photo-1505691938895-1758d7feb511?q=80&w=1200&auto=format&fit=crop",
                    "https://images.unsplash.com/photo-1494526585095-c41746248156?q=80&w=1200&auto=format&fit=crop",
                ],
                agent_name="Ayesha Khan",
                agent_rera="BRN 48291",
                agent_phone="+971 50 123 4567",
                agent_whatsapp="https://wa.me/971501234567",
                handover_year=2022,
                floor=7,
                view="Community",
            ),
        )

    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
