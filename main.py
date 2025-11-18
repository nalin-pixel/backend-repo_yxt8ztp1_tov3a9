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
    faqs = _collection("propertyfaq")

    def ensure_area(a: Area):
        if not areas.find_one({"slug": a.slug}):
            create_document("area", a)

    def ensure_listing(l: PropertyListing):
        if not listings.find_one({"slug": l.slug}):
            create_document("propertylisting", l)

    # Seed areas
    ensure_area(
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
        )
    )

    ensure_area(
        Area(
            name="Dubai Marina",
            emirate="Dubai",
            slug="dubai-marina",
            intro="Iconic waterfront community known for high-rise living and marina views.",
            avg_psf=1900.0,
            avg_price_1br=1200000,
            avg_price_2br=2000000,
            avg_price_3br=3200000,
            rental_yield_pct=6.2,
            latitude=25.0800,
            longitude=55.1400,
            tags=["waterfront", "nightlife", "investor favorite"],
        )
    )

    ensure_area(
        Area(
            name="Jumeirah Village Circle",
            emirate="Dubai",
            slug="jvc",
            intro="Popular mid-market community with strong rental demand and new projects.",
            avg_psf=1000.0,
            avg_price_1br=700000,
            avg_price_2br=1000000,
            avg_price_3br=1700000,
            rental_yield_pct=7.0,
            latitude=25.0600,
            longitude=55.2200,
            tags=["value", "mid-market", "high yield"],
        )
    )

    ensure_area(
        Area(
            name="Downtown Dubai",
            emirate="Dubai",
            slug="downtown-dubai",
            intro="Prestige address around Burj Khalifa and Dubai Mall.",
            avg_psf=2500.0,
            avg_price_1br=1800000,
            avg_price_2br=3000000,
            avg_price_3br=5000000,
            rental_yield_pct=5.5,
            latitude=25.1975,
            longitude=55.2744,
            tags=["premium", "tourist hotspot", "landmark"],
        )
    )

    ensure_area(
        Area(
            name="Palm Jumeirah",
            emirate="Dubai",
            slug="palm-jumeirah",
            intro="World-famous man-made island offering beachfront living.",
            avg_psf=3000.0,
            avg_price_1br=2200000,
            avg_price_2br=3500000,
            avg_price_3br=6000000,
            rental_yield_pct=5.0,
            latitude=25.1122,
            longitude=55.1389,
            tags=["beachfront", "luxury", "iconic"],
        )
    )

    ensure_area(
        Area(
            name="Jumeirah Lake Towers",
            emirate="Dubai",
            slug="jlt",
            intro="Clustered high-rises around lakes with strong end-user demand.",
            avg_psf=1300.0,
            avg_price_1br=900000,
            avg_price_2br=1500000,
            avg_price_3br=2200000,
            rental_yield_pct=6.8,
            latitude=25.0746,
            longitude=55.1400,
            tags=["metro", "mixed-use", "affordable"],
        )
    )

    # Seed listings
    ensure_listing(
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
        )
    )

    ensure_listing(
        PropertyListing(
            listing_id="DM-MARINA-1BR-67890",
            status="Available",
            transaction_type="Sale",
            property_type="Apartment",
            bedrooms=1,
            bathrooms=1,
            bua_sqft=780,
            price_aed=1250000,
            service_charges_aed_psf=20.0,
            emirate="Dubai",
            area="Dubai Marina",
            building="Marina Gate",
            area_slug="dubai-marina",
            title="Marina View 1BR in Marina Gate",
            slug="1br-apartment-marina-gate-dubai-marina-67890",
            seo_title="1BR Marina Gate, Dubai Marina | Marina View | AED 1.25M",
            seo_description="Well-maintained 1 bedroom with full marina view. High rental demand.",
            canonical_url="/property/1br-apartment-marina-gate-dubai-marina-67890",
            description_html="<p>High-floor unit with balcony overlooking the Marina. Walk to the promenade.</p>",
            highlights=["Full Marina View", "High Floor", "Ready to move"],
            tags=["view", "investor"],
            main_image="https://images.unsplash.com/photo-1502005229762-cf1b2da7c8e7?q=80&w=1200&auto=format&fit=crop",
            gallery_images=[
                "https://images.unsplash.com/photo-1493809842364-78817add7ffb?q=80&w=1200&auto=format&fit=crop",
                "https://images.unsplash.com/photo-1523217582562-09d0def993a6?q=80&w=1200&auto=format&fit=crop",
            ],
            agent_name="Omar Hassan",
            agent_rera="BRN 39512",
            agent_phone="+971 52 222 3344",
            agent_whatsapp="https://wa.me/971522223344",
            handover_year=2019,
            floor=28,
            view="Marina",
        )
    )

    ensure_listing(
        PropertyListing(
            listing_id="JVC-TH-3BR-24680",
            status="Available",
            transaction_type="Sale",
            property_type="Townhouse",
            bedrooms=3,
            bathrooms=4,
            bua_sqft=2200,
            price_aed=2200000,
            service_charges_aed_psf=3.5,
            emirate="Dubai",
            area="Jumeirah Village Circle",
            building="District 12",
            area_slug="jvc",
            title="Upgraded 3BR Townhouse in JVC District 12",
            slug="3br-townhouse-district-12-jvc-dubai-24680",
            seo_title="Upgraded 3BR Townhouse JVC | 2,200 sqft | AED 2.2M",
            seo_description="Family-friendly upgraded townhouse with maid's room and covered parking.",
            canonical_url="/property/3br-townhouse-district-12-jvc-dubai-24680",
            description_html="<p>Spacious townhouse with upgraded kitchen and flooring. Close to parks and schools.</p>",
            highlights=["Upgraded", "Maid's Room", "Covered Parking"],
            tags=["family", "value"],
            main_image="https://images.unsplash.com/photo-1501183638710-841dd1904471?q=80&w=1200&auto=format&fit=crop",
            gallery_images=[
                "https://images.unsplash.com/photo-1502005229762-9a5b68cd0b02?q=80&w=1200&auto=format&fit=crop",
                "https://images.unsplash.com/photo-1505691723518-36a1f2fba8e5?q=80&w=1200&auto=format&fit=crop",
            ],
            agent_name="Sarah Lee",
            agent_rera="BRN 51234",
            agent_phone="+971 58 777 8890",
            agent_whatsapp="https://wa.me/971587778890",
            handover_year=2016,
            floor=1,
            view="Community",
        )
    )

    ensure_listing(
        PropertyListing(
            listing_id="DT-OPERA-1BR-11223",
            status="Available",
            transaction_type="Sale",
            property_type="Apartment",
            bedrooms=1,
            bathrooms=1,
            bua_sqft=900,
            price_aed=2100000,
            service_charges_aed_psf=22.0,
            emirate="Dubai",
            area="Downtown Dubai",
            building="Opera Grand",
            area_slug="downtown-dubai",
            title="Burj & Fountain View 1BR in Opera Grand",
            slug="1br-apartment-opera-grand-downtown-dubai-11223",
            seo_title="1BR Opera Grand | Burj & Fountain View | AED 2.1M",
            seo_description="Premium Downtown living with iconic views. Ideal pied-à-terre or investment.",
            canonical_url="/property/1br-apartment-opera-grand-downtown-dubai-11223",
            description_html="<p>Elegant finishes, floor-to-ceiling windows, and direct access to the Boulevard.</p>",
            highlights=["Burj View", "Fountain View", "High-end Finishes"],
            tags=["luxury", "prime"],
            main_image="https://images.unsplash.com/photo-1484154218962-a197022b5858?q=80&w=1200&auto=format&fit=crop",
            gallery_images=[
                "https://images.unsplash.com/photo-1496317899792-9d7dbcd928a1?q=80&w=1200&auto=format&fit=crop",
                "https://images.unsplash.com/photo-1499951360447-b19be8fe80f5?q=80&w=1200&auto=format&fit=crop",
            ],
            agent_name="Mohammed Ali",
            agent_rera="BRN 40291",
            agent_phone="+971 55 999 0011",
            agent_whatsapp="https://wa.me/971559990011",
            handover_year=2020,
            floor=35,
            view="Burj & Fountain",
        )
    )

    ensure_listing(
        PropertyListing(
            listing_id="PALM-VILLA-4BR-99887",
            status="Available",
            transaction_type="Sale",
            property_type="Villa",
            bedrooms=4,
            bathrooms=5,
            bua_sqft=5200,
            price_aed=18000000,
            service_charges_aed_psf=4.0,
            emirate="Dubai",
            area="Palm Jumeirah",
            building="Garden Homes",
            area_slug="palm-jumeirah",
            title="Beachfront 4BR Garden Home on Palm",
            slug="4br-villa-garden-homes-palm-jumeirah-dubai-99887",
            seo_title="Beachfront 4BR Garden Home, Palm Jumeirah | AED 18M",
            seo_description="Private beach access, skyline views, and premium finishes. A rare opportunity.",
            canonical_url="/property/4br-villa-garden-homes-palm-jumeirah-dubai-99887",
            description_html="<p>Immaculate villa with pool, landscaped garden, and direct beach access.</p>",
            highlights=["Beachfront", "Private Pool", "Skyline View"],
            tags=["ultra luxury", "waterfront"],
            main_image="https://images.unsplash.com/photo-1515266591878-f93e32bc5937?q=80&w=1200&auto=format&fit=crop",
            gallery_images=[
                "https://images.unsplash.com/photo-1494526585095-c41746248156?q=80&w=1200&auto=format&fit=crop",
                "https://images.unsplash.com/photo-1507089947368-19c1da9775ae?q=80&w=1200&auto=format&fit=crop",
            ],
            agent_name="Layla Noor",
            agent_rera="BRN 37777",
            agent_phone="+971 56 111 2223",
            agent_whatsapp="https://wa.me/971561112223",
            handover_year=2010,
            floor=2,
            view="Sea & Skyline",
        )
    )

    ensure_listing(
        PropertyListing(
            listing_id="JLT-ST-00077",
            status="Available",
            transaction_type="Sale",
            property_type="Apartment",
            bedrooms=0.0,
            bathrooms=1,
            bua_sqft=420,
            price_aed=580000,
            service_charges_aed_psf=18.0,
            emirate="Dubai",
            area="Jumeirah Lake Towers",
            building="Lake Terrace",
            area_slug="jlt",
            title="Furnished Studio in JLT Lake Terrace",
            slug="studio-apartment-lake-terrace-jlt-dubai-00077",
            seo_title="Furnished Studio Lake Terrace JLT | AED 580K",
            seo_description="Great starter or investment unit with lake view and balcony.",
            canonical_url="/property/studio-apartment-lake-terrace-jlt-dubai-00077",
            description_html="<p>Compact, fully furnished studio ideal for investors. Close to metro.</p>",
            highlights=["Furnished", "Lake View", "Near Metro"],
            tags=["entry", "yield"],
            main_image="https://images.unsplash.com/photo-1460317442991-0ec209397118?q=80&w=1200&auto=format&fit=crop",
            gallery_images=[
                "https://images.unsplash.com/photo-1499951360447-b19be8fe80f5?q=80&w=1200&auto=format&fit=crop",
                "https://images.unsplash.com/photo-1493809842364-78817add7ffb?q=80&w=1200&auto=format&fit=crop",
            ],
            agent_name="Heba Farouk",
            agent_rera="BRN 48888",
            agent_phone="+971 50 333 4456",
            agent_whatsapp="https://wa.me/971503334456",
            handover_year=2008,
            floor=14,
            view="Lake",
        )
    )

    # Seed a simple FAQ for two listings
    def ensure_faq(slug: str, faqs_list: list):
        if not faqs.find_one({"listing_slug": slug}):
            create_document(
                "propertyfaq",
                PropertyFAQ(listing_slug=slug, faqs=faqs_list),
            )

    ensure_faq(
        "2br-apartment-avenue-residence-4-al-furjan-dubai-12345",
        [
            {"question": "Is the unit vacant?", "answer": "Yes, vacant on transfer."},
            {"question": "Nearest metro?", "answer": "Al Furjan (Route 2020) approximately 5 minutes walk."},
        ],
    )

    ensure_faq(
        "1br-apartment-marina-gate-dubai-marina-67890",
        [
            {"question": "Does it have a marina view?", "answer": "Yes, full marina view from the balcony."},
            {"question": "Service charges?", "answer": "Approx. AED 20 per sqft annually."},
        ],
    )

    return {"status": "ok", "areas": areas.count_documents({}), "listings": listings.count_documents({})}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
