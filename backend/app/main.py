from fastapi import FastAPI, WebSocket, Depends, HTTPException, status, Query, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import timedelta
from jose import jwt

from . import models, schemas, auth
from .database import SessionLocal, engine
from .translate import translate_text

# Create database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI()

# Update CORS configuration with more specific settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: int):
        self.active_connections.pop(user_id, None)

    async def send_personal_message(self, message: dict, user_id: int):
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_json(message)

manager = ConnectionManager()

@app.post("/register", response_model=schemas.User)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = auth.get_user(db, username=user.username)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    hashed_password = auth.get_password_hash(user.password)
    db_user = models.User(
        username=user.username,
        password=hashed_password,
        language=user.language
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.post("/token", response_model=schemas.Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(auth.get_db)
):
    user = auth.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me", response_model=schemas.User)
async def read_users_me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user

@app.get("/users", response_model=List[schemas.User])
async def get_users(
    db: Session = Depends(auth.get_db),
    current_user: models.User = Depends(auth.get_current_user),
    skip: int = 0,
    limit: int = 100
):
    users = db.query(models.User).offset(skip).limit(limit).all()
    return users

@app.get("/messages/{user_id}", response_model=List[schemas.Message])
async def get_messages(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
    local_kw: Optional[bool] = Query(None)
):
    messages = db.query(models.Message).filter(
        ((models.Message.sender_id == current_user.id) & 
         (models.Message.receiver_id == user_id)) |
        ((models.Message.sender_id == user_id) & 
         (models.Message.receiver_id == current_user.id))
    ).all()
    return messages

@app.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str):
    try:
        # Verify JWT token before accepting connection
        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        username = payload.get("sub")
        if not username:
            await websocket.close(code=1008)
            return
        
        db = SessionLocal()
        try:
            user = auth.get_user(db, username=username)
            if not user:
                await websocket.close(code=1008)
                return
                
            await manager.connect(websocket, user.id)
            
            while True:
                data = await websocket.receive_json()
                receiver = db.query(models.User).filter(models.User.id == data["receiver_id"]).first()
                if receiver:
                    translated = await translate_text(data["message"], receiver.language)
                    message = models.Message(
                        sender_id=user.id,
                        receiver_id=data["receiver_id"],
                        original_message=data["message"],
                        translated_message=translated
                    )
                    db.add(message)
                    db.commit()
                    db.refresh(message)
                    
                    await manager.send_personal_message(
                        {
                            "id": message.id,
                            "sender_id": user.id,
                            "receiver_id": data["receiver_id"],
                            "original_message": message.original_message,
                            "translated_message": message.translated_message,
                            "timestamp": str(message.timestamp)
                        },
                        data["receiver_id"]
                    )
                
        finally:
            db.close()
            
    except Exception as e:
        print(f"WebSocket error: {e}")
        if 'user' in locals():
            manager.disconnect(user.id)