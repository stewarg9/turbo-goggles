import os
import shutil
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import FastAPI, Depends, Request, Form, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import sqlite3

from app.database import get_db, init_db

app = FastAPI(title="Pi Recipe Engine")

# Static files & Templates
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

@app.on_event("startup")
def startup():
    init_db()

# --- Pydantic Schemas for AI Import Endpoint ---
class ImportIngredient(BaseModel):
    raw_text: str
    normalized_name: str
    quantity: Optional[float] = None
    unit: Optional[str] = None
    prep_note: Optional[str] = None
    category: Optional[str] = "Pantry"
    is_store_cupboard: bool = False

class ImportRecipePayload(BaseModel):
    title: str
    preamble: Optional[str] = None
    method: str
    postamble: Optional[str] = None
    source_type: Optional[str] = "other"
    source_name: Optional[str] = None
    source_detail: Optional[str] = None
    source_url: Optional[str] = None
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    servings: Optional[int] = 4
    tags: List[str] = []
    ingredients: List[ImportIngredient] = []

# --- AI Recipe Import API ---
@app.post("/api/recipes/import")
def import_recipe(payload: ImportRecipePayload, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    
    # 1. Insert Recipe Core
    cursor.execute("""
        INSERT INTO recipes (title, preamble, method, postamble, source_type, source_name, source_detail, source_url, prep_time_minutes, cook_time_minutes, servings)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (payload.title, payload.preamble, payload.method, payload.postamble, payload.source_type, payload.source_name, payload.source_detail, payload.source_url, payload.prep_time_minutes, payload.cook_time_minutes, payload.servings))
    recipe_id = cursor.lastrowid

    # 2. Process Ingredients
    for ing in payload.ingredients:
        # Upsert normalized ingredient
        cursor.execute("SELECT id FROM ingredients WHERE LOWER(name) = LOWER(?)", (ing.normalized_name,))
        row = cursor.fetchone()
        if row:
            ing_id = row["id"]
        else:
            cursor.execute("INSERT INTO ingredients (name, category, is_store_cupboard) VALUES (?, ?, ?)",
                           (ing.normalized_name.title(), ing.category, ing.is_store_cupboard))
            ing_id = cursor.lastrowid
        
        # Link to recipe
        cursor.execute("""
            INSERT INTO recipe_ingredients (recipe_id, ingredient_id, raw_text, quantity, unit, prep_note)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (recipe_id, ing_id, ing.raw_text, ing.quantity, ing.unit, ing.prep_note))

    # 3. Process Tags
    for tag_name in payload.tags:
        cursor.execute("SELECT id FROM tags WHERE LOWER(name) = LOWER(?)", (tag_name,))
        t_row = cursor.fetchone()
        if t_row:
            tag_id = t_row["id"]
        else:
            cursor.execute("INSERT INTO tags (name) VALUES (?)", (tag_name.title(),))
            tag_id = cursor.lastrowid
        cursor.execute("INSERT OR IGNORE INTO recipe_tags (recipe_id, tag_id) VALUES (?, ?)", (recipe_id, tag_id))

    db.commit()
    return {"status": "success", "recipe_id": recipe_id, "message": f"Imported '{payload.title}' successfully."}

# --- Web UI Routes ---
@app.get("/", response_class=HTMLResponse)
def index(request: Request, q: Optional[str] = None, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    if q:
        cursor.execute("SELECT * FROM recipes WHERE title LIKE ? ORDER BY title ASC", (f"%{q}%",))
    else:
        cursor.execute("SELECT * FROM recipes ORDER BY id DESC")
    recipes = cursor.fetchall()
    return templates.TemplateResponse("recipes.html", {"request": request, "recipes": recipes, "search_q": q or ""})

@app.get("/recipe/{recipe_id}", response_class=HTMLResponse)
def recipe_detail(request: Request, recipe_id: int, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,))
    recipe = cursor.fetchone()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    
    cursor.execute("""
        SELECT ri.*, i.name as ingredient_name, i.is_store_cupboard 
        FROM recipe_ingredients ri
        JOIN ingredients i ON ri.ingredient_id = i.id
        WHERE ri.recipe_id = ?
    """, (recipe_id,))
    ingredients = cursor.fetchall()

    cursor.execute("""
        SELECT rc.*, r.title as companion_title 
        FROM recipe_companions rc
        LEFT JOIN recipes r ON rc.companion_recipe_id = r.id
        WHERE rc.recipe_id = ?
    """, (recipe_id,))
    companions = cursor.fetchall()

    return templates.TemplateResponse("recipe_detail.html", {
        "request": request, "recipe": recipe, "ingredients": ingredients, "companions": companions
    })

@app.get("/planner", response_class=HTMLResponse)
def planner_view(request: Request, start_date: Optional[str] = None, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    today = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else datetime.now().date()
    # Align to Monday
    monday = today - timedelta(days=today.weekday())
    week_dates = [monday + timedelta(days=i) for i in range(7)]

    cursor.execute("SELECT * FROM recipes ORDER BY title ASC")
    all_recipes = cursor.fetchall()

    # Get planned items for current week
    cursor.execute("""
        SELECT mp.plan_date, mpi.id as item_id, mpi.servings, r.id as recipe_id, r.title, mpi.custom_item
        FROM meal_plans mp
        JOIN meal_plan_items mpi ON mp.id = mpi.meal_plan_id
        LEFT JOIN recipes r ON mpi.recipe_id = r.id
        WHERE mp.plan_date BETWEEN ? AND ?
    """, (week_dates[0].strftime("%Y-%m-%d"), week_dates[-1].strftime("%Y-%m-%d")))
    planned_rows = cursor.fetchall()

    schedule = {d.strftime("%Y-%m-%d"): [] for d in week_dates}
    for row in planned_rows:
        schedule[row["plan_date"]].append(row)

    return templates.TemplateResponse("planner.html", {
        "request": request, "week_dates": week_dates, "schedule": schedule, "all_recipes": all_recipes
    })

@app.post("/planner/add")
def add_to_planner(
    plan_date: str = Form(...),
    recipe_id: Optional[int] = Form(None),
    companions: List[str] = Form([]),
    db: sqlite3.Connection = Depends(get_db)
):
    cursor = db.cursor()
    cursor.execute("INSERT INTO meal_plans (plan_date) VALUES (?)", (plan_date,))
    plan_id = cursor.lastrowid

    if recipe_id:
        cursor.execute("INSERT INTO meal_plan_items (meal_plan_id, recipe_id) VALUES (?, ?)", (plan_id, recipe_id))

    for comp in companions:
        if comp.startswith("recipe_"):
            comp_rec_id = int(comp.replace("recipe_", ""))
            cursor.execute("INSERT INTO meal_plan_items (meal_plan_id, recipe_id) VALUES (?, ?)", (plan_id, comp_rec_id))
        else:
            cursor.execute("INSERT INTO meal_plan_items (meal_plan_id, custom_item) VALUES (?, ?)", (plan_id, comp))

    db.commit()
    return RedirectResponse(url=f"/planner?start_date={plan_date}", status_code=303)

@app.get("/shopping", response_class=HTMLResponse)
def shopping_list(
    request: Request,
    start_date: Optional[str] = None,
    days: int = 7,
    db: sqlite3.Connection = Depends(get_db)
):
    start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else datetime.now().date()
    end = start + timedelta(days=days - 1)

    cursor = db.cursor()
    cursor.execute("""
        SELECT 
            i.name as ingredient,
            i.category,
            i.is_store_cupboard,
            SUM(ri.quantity) as total_qty,
            ri.unit
        FROM meal_plans mp
        JOIN meal_plan_items mpi ON mp.id = mpi.meal_plan_id
        JOIN recipe_ingredients ri ON mpi.recipe_id = ri.recipe_id
        JOIN ingredients i ON ri.ingredient_id = i.id
        WHERE mp.plan_date BETWEEN ? AND ?
        GROUP BY i.id, ri.unit
        ORDER BY i.category ASC, i.name ASC
    """, (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
    
    ingredients = cursor.fetchall()
    
    fresh_items = [item for item in ingredients if not item["is_store_cupboard"]]
    cupboard_items = [item for item in ingredients if item["is_store_cupboard"]]

    return templates.TemplateResponse("shopping.html", {
        "request": request, "fresh_items": fresh_items, "cupboard_items": cupboard_items,
        "start_date": start, "end_date": end
    })

@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    return templates.TemplateResponse("import.html", {"request": request})
