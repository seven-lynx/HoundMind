#!/usr/bin/env python3
"""
Face Recognition Service for PackMind
====================================

Advanced face detection, recognition, and memory system for personal interaction.
Builds personality profiles and adapts behavior based on individual relationships.

Features:
- Real-time face detection using camera
- Face encoding and recognition database
- Interaction memory and relationship tracking  
- Personality adaptation per person
- Privacy-conscious local processing

Author: 7Lynx
Version: 2025.10.24.1
"""

import cv2
import numpy as np
import json
import time
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False
    logging.warning("face_recognition not available - face recognition disabled")

try:
    import pickle
    PICKLE_AVAILABLE = True
except ImportError:
    PICKLE_AVAILABLE = False


@dataclass
class PersonProfile:
    """Profile for a recognized person"""
    person_id: str
    name: str = "Unknown"
    first_seen: str = ""
    last_seen: str = ""
    interaction_count: int = 0
    favorite_interactions: Optional[List[str]] = None
    personality_traits: Optional[Dict[str, float]] = None
    face_encoding: Optional[np.ndarray] = None
    
    def __post_init__(self):
        if self.favorite_interactions is None:
            self.favorite_interactions = []
        if self.personality_traits is None:
            self.personality_traits = {
                "friendliness": 0.5,
                "playfulness": 0.5, 
                "energy_level": 0.5,
                "patience": 0.5
            }
        if not self.first_seen:
            self.first_seen = datetime.now().isoformat()


@dataclass
class InteractionEvent:
    """Record of an interaction with a person"""
    person_id: str
    timestamp: str
    interaction_type: str
    duration: float
    emotional_response: str
    context: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.context is None:
            self.context = {}


class FaceRecognitionService:
    """
    Advanced face recognition service with memory and personality adaptation
    """
    
    def __init__(self, config=None):
        """Initialize face recognition service"""
        self.config = config or {}
        self.logger = logging.getLogger("packmind.face_recognition")
        
        # Service state
        self.enabled = FACE_RECOGNITION_AVAILABLE and self.config.get("ENABLE_FACE_RECOGNITION", True)
        self.running = False
        
        # Recognition parameters
        self.recognition_threshold = self.config.get("FACE_RECOGNITION_THRESHOLD", 0.6)
        self.detection_interval = self.config.get("FACE_DETECTION_INTERVAL", 2.0)  # seconds
        # Configurable limits and camera settings
        self.max_faces_per_frame = self.config.get("FACE_MAX_FACES_PER_FRAME", 3)
        
        # Storage paths
        self.data_dir = Path(self.config.get("FACE_DATA_DIR", "data/faces"))
        self.profiles_file = self.data_dir / "profiles.json"
        self.interactions_file = self.data_dir / "interactions.json"
        self.encodings_file = self.data_dir / "encodings.pkl"
        
        # Create data directory
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Data structures
        self.known_faces = {}  # person_id -> PersonProfile
        self.face_encodings = {}  # person_id -> face_encoding
        self.interaction_history = []  # List of InteractionEvent
        self.current_faces = {}  # Currently visible faces
        
        # Camera state
        self.camera = None
        self.last_detection_time = 0
        
        # Performance tracking
        self.recognition_stats = {
            "detections": 0,
            "recognitions": 0,
            "new_faces": 0,
            "processing_time": []
        }
        
        if self.enabled:
            self.logger.info("Face Recognition Service initialized successfully")
            self._load_data()
        else:
            self.logger.warning("Face Recognition Service disabled - missing dependencies")
    
    def start(self):
        """Start the face recognition service"""
        if not self.enabled:
            self.logger.warning("Cannot start - face recognition not available")
            return False
            
        try:
            self.running = True
            self._initialize_camera()
            self.logger.info("Face Recognition Service started")
            return True
        except Exception as e:
            self.logger.error(f"Failed to start face recognition service: {e}")
            self.running = False
            return False
    
    def stop(self):
        """Stop the face recognition service"""
        self.running = False
        if self.camera:
            self.camera.release()
            self.camera = None
        self._save_data()
        self.logger.info("Face Recognition Service stopped")
    
    def _initialize_camera(self):
        """Initialize camera for face detection"""
        try:
            self.camera = cv2.VideoCapture(0)  # Use default camera
            if not self.camera.isOpened():
                raise RuntimeError("Could not open camera")
                
            # Set camera properties for better performance
            width = int(self.config.get("FACE_CAMERA_WIDTH", 640))
            height = int(self.config.get("FACE_CAMERA_HEIGHT", 480))
            fps = int(self.config.get("FACE_CAMERA_FPS", 15))
            try:
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                self.camera.set(cv2.CAP_PROP_FPS, fps)
            except Exception:
                pass
            
            self.logger.info("Camera initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize camera: {e}")
            raise
    
    def detect_and_recognize(self) -> Dict[str, Any]:
        """
        Detect and recognize faces in current camera frame
        
        Returns:
            Dict with detection results and recognized persons
        """
        if not self.enabled or not self.running or not self.camera:
            return {"faces": [], "error": "Service not available"}
        
        # Throttle detection to avoid excessive processing
        current_time = time.time()
        if current_time - self.last_detection_time < self.detection_interval:
            return {"faces": list(self.current_faces.values()), "cached": True}
        
        start_time = time.time()
        
        try:
            # Capture frame
            ret, frame = self.camera.read()
            if not ret:
                return {"faces": [], "error": "Failed to capture frame"}
            
            # Convert BGR to RGB for face_recognition
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Detect faces
            face_locations = face_recognition.face_locations(rgb_frame, model="hog")
            
            if not face_locations:
                self.current_faces = {}
                return {"faces": [], "frame_time": time.time() - start_time}
            
            # Limit number of faces processed
            if len(face_locations) > self.max_faces_per_frame:
                face_locations = face_locations[:self.max_faces_per_frame]
            
            # Encode faces
            face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
            
            detected_faces = []
            
            # Process each detected face
            for i, (face_encoding, face_location) in enumerate(zip(face_encodings, face_locations)):
                # Try to recognize face
                person_id, confidence = self._recognize_face(face_encoding)
                
                if person_id:
                    # Known person
                    person_profile = self.known_faces[person_id]
                    person_profile.last_seen = datetime.now().isoformat()
                    person_profile.interaction_count += 1
                    
                    face_info = {
                        "person_id": person_id,
                        "name": person_profile.name,
                        "confidence": confidence,
                        "location": face_location,
                        "known": True,
                        "interaction_count": person_profile.interaction_count
                    }
                else:
                    # Unknown person - create new profile
                    person_id = self._create_new_person(face_encoding)
                    
                    face_info = {
                        "person_id": person_id,
                        "name": f"Person_{person_id[:8]}",
                        "confidence": 0.0,
                        "location": face_location,
                        "known": False,
                        "interaction_count": 1
                    }
                
                detected_faces.append(face_info)
                self.current_faces[person_id] = face_info
            
            self.last_detection_time = current_time
            processing_time = time.time() - start_time
            self.recognition_stats["processing_time"].append(processing_time)
            self.recognition_stats["detections"] += len(detected_faces)
            
            return {
                "faces": detected_faces,
                "frame_time": processing_time,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Error during face detection: {e}")
            return {"faces": [], "error": str(e)}
    
    def _recognize_face(self, face_encoding: np.ndarray) -> Tuple[Optional[str], float]:
        """
        Recognize a face encoding against known faces
        
        Args:
            face_encoding: Face encoding to recognize
            
        Returns:
            Tuple of (person_id, confidence) or (None, 0.0) if not recognized
        """
        if not self.face_encodings:
            return None, 0.0
        
        # Compare against all known faces
        known_encodings = list(self.face_encodings.values())
        known_ids = list(self.face_encodings.keys())
        
        # Calculate distances
        distances = face_recognition.face_distance(known_encodings, face_encoding)
        
        # Find best match
        best_match_index = np.argmin(distances)
        best_distance = distances[best_match_index]
        
        # Check if distance is below threshold
        if best_distance <= self.recognition_threshold:
            person_id = known_ids[best_match_index]
            confidence = 1.0 - best_distance  # Convert distance to confidence
            self.recognition_stats["recognitions"] += 1
            return person_id, confidence
        
        return None, 0.0
    
    def _create_new_person(self, face_encoding: np.ndarray) -> str:
        """
        Create a new person profile for an unknown face
        
        Args:
            face_encoding: Face encoding for the new person
            
        Returns:
            Generated person_id
        """
        # Generate unique person ID
        person_id = f"person_{int(time.time())}_{len(self.known_faces)}"
        
        # Create profile
        profile = PersonProfile(
            person_id=person_id,
            name=f"Person_{person_id[:8]}",
            face_encoding=face_encoding
        )
        
        # Store profile and encoding
        self.known_faces[person_id] = profile
        self.face_encodings[person_id] = face_encoding
        
        self.recognition_stats["new_faces"] += 1
        self.logger.info(f"Created new person profile: {person_id}")
        
        return person_id
    
    def record_interaction(self, person_id: str, interaction_type: str, 
                         duration: float = 0.0, emotional_response: str = "neutral",
                         context: Optional[Dict[str, Any]] = None):
        """
        Record an interaction with a person
        
        Args:
            person_id: ID of person interacted with
            interaction_type: Type of interaction (touch, voice, play, etc.)
            duration: Duration of interaction in seconds
            emotional_response: Emotional response (happy, excited, calm, etc.)
            context: Additional context information
        """
        if person_id not in self.known_faces:
            self.logger.warning(f"Attempted to record interaction with unknown person: {person_id}")
            return
        
        # Create interaction event
        interaction = InteractionEvent(
            person_id=person_id,
            timestamp=datetime.now().isoformat(),
            interaction_type=interaction_type,
            duration=duration,
            emotional_response=emotional_response,
            context=context or {}
        )
        
        self.interaction_history.append(interaction)
        
        # Update person profile
        profile = self.known_faces[person_id]
        if interaction_type not in profile.favorite_interactions:
            profile.favorite_interactions.append(interaction_type)
        
        # Update personality traits based on interaction
        self._update_personality_traits(person_id, interaction_type, emotional_response)
        
        self.logger.info(f"Recorded {interaction_type} interaction with {person_id}")
    
    def _update_personality_traits(self, person_id: str, interaction_type: str, 
                                 emotional_response: str):
        """Update personality traits based on interaction patterns"""
        profile = self.known_faces[person_id]
        traits = profile.personality_traits
        
        # Adjust traits based on interaction type and response
        adjustments = {
            "touch": {"friendliness": 0.1, "patience": 0.05},
            "play": {"playfulness": 0.15, "energy_level": 0.1},
            "voice": {"friendliness": 0.05, "patience": 0.1},
            "training": {"patience": 0.2}
        }
        
        # Emotional response modifiers
        emotion_modifiers = {
            "happy": 1.5,
            "excited": 2.0,
            "calm": 1.0,
            "neutral": 0.5,
            "annoyed": -0.5
        }
        
        modifier = emotion_modifiers.get(emotional_response, 1.0)
        
        if interaction_type in adjustments:
            for trait, adjustment in adjustments[interaction_type].items():
                current_value = traits.get(trait, 0.5)
                new_value = np.clip(current_value + (adjustment * modifier), 0.0, 1.0)
                traits[trait] = new_value
    
    def get_person_profile(self, person_id: str) -> Optional[PersonProfile]:
        """Get profile for a specific person"""
        return self.known_faces.get(person_id)
    
    def get_interaction_history(self, person_id: Optional[str] = None, 
                              days: int = 7) -> List[InteractionEvent]:
        """
        Get interaction history
        
        Args:
            person_id: Filter by person ID (None for all)
            days: Number of days to look back
            
        Returns:
            List of interaction events
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        
        filtered_interactions = []
        for interaction in self.interaction_history:
            interaction_date = datetime.fromisoformat(interaction.timestamp)
            
            if interaction_date < cutoff_date:
                continue
                
            if person_id and interaction.person_id != person_id:
                continue
                
            filtered_interactions.append(interaction)
        
        return filtered_interactions
    
    def get_recognition_stats(self) -> Dict[str, Any]:
        """Get service performance statistics"""
        stats = self.recognition_stats.copy()
        
        if stats["processing_time"]:
            stats["avg_processing_time"] = np.mean(stats["processing_time"])
            stats["max_processing_time"] = max(stats["processing_time"])
        
        stats["known_persons"] = len(self.known_faces)
        stats["total_interactions"] = len(self.interaction_history)
        
        return stats
    
    def update_person_name(self, person_id: str, name: str):
        """Update the name for a recognized person"""
        if person_id in self.known_faces:
            self.known_faces[person_id].name = name
            self.logger.info(f"Updated name for {person_id}: {name}")
    
    def _load_data(self):
        """Load stored face recognition data"""
        try:
            # Load profiles
            if self.profiles_file.exists():
                with open(self.profiles_file, 'r') as f:
                    profiles_data = json.load(f)
                    
                for person_id, profile_dict in profiles_data.items():
                    profile = PersonProfile(**profile_dict)
                    self.known_faces[person_id] = profile
            
            # Load face encodings
            if self.encodings_file.exists() and PICKLE_AVAILABLE:
                with open(self.encodings_file, 'rb') as f:
                    self.face_encodings = pickle.load(f)
            
            # Load interaction history
            if self.interactions_file.exists():
                with open(self.interactions_file, 'r') as f:
                    interactions_data = json.load(f)
                    
                self.interaction_history = [
                    InteractionEvent(**interaction_dict) 
                    for interaction_dict in interactions_data
                ]
            
            self.logger.info(f"Loaded {len(self.known_faces)} person profiles and "
                           f"{len(self.interaction_history)} interactions")
            
        except Exception as e:
            self.logger.error(f"Error loading face recognition data: {e}")
    
    def _save_data(self):
        """Save face recognition data to disk"""
        try:
            # Save profiles (excluding face encodings)
            profiles_data = {}
            for person_id, profile in self.known_faces.items():
                profile_dict = asdict(profile)
                profile_dict.pop('face_encoding', None)  # Remove encoding from JSON
                profiles_data[person_id] = profile_dict
            
            with open(self.profiles_file, 'w') as f:
                json.dump(profiles_data, f, indent=2)
            
            # Save face encodings separately (binary)
            if PICKLE_AVAILABLE:
                with open(self.encodings_file, 'wb') as f:
                    pickle.dump(self.face_encodings, f)
            
            # Save interaction history
            interactions_data = [asdict(interaction) for interaction in self.interaction_history]
            with open(self.interactions_file, 'w') as f:
                json.dump(interactions_data, f, indent=2)
            
            self.logger.info("Face recognition data saved successfully")
            
        except Exception as e:
            self.logger.error(f"Error saving face recognition data: {e}")


# Convenience functions for easy integration
def create_face_recognition_service(config=None):
    """Factory function to create face recognition service"""
    return FaceRecognitionService(config)


if __name__ == "__main__":
    # Test the service
    import sys
    logging.basicConfig(level=logging.INFO)
    
    service = FaceRecognitionService()
    
    if service.start():
        print("Face Recognition Service started successfully")
        print("Press Ctrl+C to stop")
        
        try:
            while True:
                result = service.detect_and_recognize()
                
                if result["faces"]:
                    for face in result["faces"]:
                        print(f"Detected: {face['name']} "
                              f"(confidence: {face['confidence']:.2f}, "
                              f"known: {face['known']})")
                
                time.sleep(1)
                
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            service.stop()
    else:
        print("Failed to start Face Recognition Service")
        sys.exit(1)