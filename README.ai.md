 `README.ai.md` (English - For AI Agents, Token-Optimized)

```markdown
# ROE: Route Optimization Engine

## PROJECT_TYPE
Academic web app | CVRPTW solver | 3-person team | KMITL

## PROBLEM
Manual/FCFS route assignment → long inter-zone legs, excess vehicles, late deliveries.

## SOLUTION
OR-Tools CVRPTW solver. 5 constraints: time_windows, vehicle_capacity, distance_min, fleet_min, GLS_penalty(anti-local-optima).

## STACK
```
frontend: HTML/CSS/JS(vanilla) + Leaflet.js(map) + Chart.js(metrics)
backend: FastAPI(python3.11+) + SQLAlchemy
db: PostgreSQL + PostGIS
optimizer: Google OR-Tools (routing_enums_pb2, pywrapcp)
distance: OSRM (self-hosted) | fallback: Haversine
deploy: Docker + docker-compose
```

## ARCHITECTURE
```
frontend --HTTP/JSON--> backend/api --> optimizer(ortools) --> distance_service --> OSRM
                              |
                              v
                        postgresql+postgis
```

## FILE_STRUCTURE
```
frontend/
  index.html, css/{style,map}.css, js/{main,map,api,dashboard}.js
backend/
  app.py                    # FastAPI entry
  config.py                 # DB config
  models.py                 # Pydantic + ORM models
  database.py               # DB connection
  api/
    orders.py                 # CRUD orders
    vehicles.py                # CRUD vehicles
    optimization.py            # POST /optimize
  services/
    optimizer.py               # CORE: ortools VRPTW solver
    distance_service.py        # distance matrix (OSRM/haversine)
    metrics.py                  # KPI calc (distance reduction %, etc)
    validation.py
database/schema.sql
docs/{SRS.md, API_SPEC.md}
```

## DATA_MODEL
```
CUSTOMER(customer_id PK, name, phone, lat, lon, address)
ORDER(order_id PK, customer_id FK, weight, time_window_start, time_window_end, status)
VEHICLE(vehicle_id PK, license_plate, max_capacity, vehicle_type, status)
ROUTE(route_id PK, vehicle_id FK, total_distance, total_duration, status)
ROUTE_ORDER(route_order_id PK, route_id FK, order_id FK, sequence, arrival_time)
USER(user_id PK, username, password_hash, role)
```

## API_ENDPOINTS
```
POST   /api/v1/orders/upload      multipart-csv -> {status, total, errors}
POST   /api/v1/orders             json -> order_id
GET    /api/v1/orders             -> order_list
DELETE /api/v1/orders/{id}        -> status

POST   /api/v1/optimize
  req: {orders:[id], vehicles:[id], depot_lat, depot_lon, timeout_seconds}
  res_success: {status, routes:[{route_id,vehicle_id,orders,total_distance,
                total_duration,waypoints:[{lat,lon}]}], summary}
  res_fail(400): {status:error, message, suggestions:[]}

GET    /api/v1/routes/{id}        -> route detail + polyline
GET    /api/v1/routes/export/json
GET    /api/v1/routes/export/csv
```

## CORE_ALGORITHM_LOGIC (optimizer.py)
```python
# Uses ortools.constraint_solver.pywrapcp
# 1. RoutingIndexManager(num_locations, num_vehicles, depot=0)
# 2. RoutingModel(manager)
# 3. distance_callback -> RegisterTransitCallback -> SetArcCostEvaluatorOfAllVehicles
# 4. demand_callback (weight) -> AddDimension("Capacity", vehicle_capacities)
# 5. time_callback -> AddDimension("Time", slack=30, max=500)
# 6. time_dimension.CumulVar(node).SetRange(start,end) per order
# 7. search_parameters:
#      first_solution_strategy = PATH_CHEAPEST_ARC
#      local_search_metaheuristic = GUIDED_LOCAL_SEARCH
#      time_limit.seconds = 30
# 8. SolveWithParameters -> extract routes or return infeasible
```

## CONSTRAINTS
```
- max_orders_per_run: ~100 (30s timeout limit)
- no_realtime_gps_tracking
- no_dynamic_reoptimization (static batch per run)
- distance_source: OpenStreetMap (may have coverage gaps)
```

## TEAM_OWNERSHIP
```
Khing (backend_db_engineer):
  - schema.sql, models.py, database.py
  - api/orders.py, api/vehicles.py
  - authentication

Arm (optimization_engineer):
  - services/optimizer.py [CRITICAL PATH]
  - services/distance_service.py
  - services/metrics.py
  - api/optimization.py

Miew (frontend_engineer):
  - index.html, css/*, js/*
  - Leaflet map integration
  - Chart.js dashboard
  - CSV/JSON export UI
```

## SETUP_COMMANDS
```bash
git clone [repo_url] && cd route-optimization-engine
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
docker-compose up -d database
python backend/database.py --init
uvicorn backend.app:app --reload --port 8000
# UI: localhost:8000 | Swagger: localhost:8000/docs
```

## TEST_COMMANDS
```bash
pytest backend/tests/
pytest backend/tests/test_optimizer.py -v
```

## SAMPLE_METRICS (placeholder, replace with actual)
```
distance_reduction: 38%
vehicle_reduction: 30%
ontime_delivery_improvement: +16%
```

## RELATED_DOCS
```
docs/SRS.md      # full requirements spec
docs/API_SPEC.md # detailed API contracts
database/schema.sql
```
```

---

