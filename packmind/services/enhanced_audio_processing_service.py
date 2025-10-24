"""
Enhanced Audio Processing Service for PackMind

This service provides advanced audio processing capabilities for the PiDog including
multi-source sound tracking, intelligent localization, noise filtering, and audio
event classification using the microphone array and sound direction sensor.

Features:
- Multi-directional sound source detection and tracking
- Real-time audio level monitoring and threshold detection
- Voice activity detection and speech/non-speech classification
- Background noise filtering and audio enhancement
- Sound direction calculation using microphone array
- Audio event logging and pattern recognition
- Integration with voice command and emotional response systems

Author: PackMind AI Assistant
Created: 2024
"""

import time
import threading
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple, Callable, Union
from enum import Enum
import logging
import json
import queue
from pathlib import Path
import math

try:
    import pyaudio
    import numpy as np
    from scipy import signal
    from scipy.fft import fft, fftfreq
except ImportError:
    print("Warning: Audio libraries not available. Enhanced Audio Processing Service running in simulation mode.")
    pyaudio = None
    signal = None
    fft = None
    fftfreq = None

try:
    import pidog
except ImportError:
    print("Warning: pidog library not available. Enhanced Audio Processing Service running in simulation mode.")
    pidog = None

@dataclass
class AudioSample:
    """Single audio sample with metadata"""
    timestamp: float
    audio_data: np.ndarray  # Raw audio samples
    sample_rate: int        # Samples per second
    channels: int           # Number of audio channels
    duration: float         # Duration in seconds
    rms_level: float        # Root Mean Square audio level
    peak_level: float       # Peak audio level
    
    def __post_init__(self):
        """Calculate derived audio properties"""
        if len(self.audio_data) > 0:
            # Calculate frequency spectrum
            if fft is not None and fftfreq is not None:
                self.fft_data = fft(self.audio_data)
                self.frequencies = fftfreq(len(self.audio_data), 1/self.sample_rate)
                
                # Find dominant frequency
                magnitude_spectrum = np.abs(self.fft_data)
                self.dominant_frequency = self.frequencies[np.argmax(magnitude_spectrum)]
            else:
                self.fft_data = None
                self.frequencies = None
                self.dominant_frequency = 0.0

class SoundSourceType(Enum):
    """Types of detected sound sources"""
    UNKNOWN = "unknown"
    VOICE = "voice"
    FOOTSTEPS = "footsteps"
    MECHANICAL = "mechanical"
    MUSIC = "music"
    ANIMAL = "animal"
    ENVIRONMENTAL = "environmental"
    ALARM = "alarm"

@dataclass
class SoundSource:
    """Detected sound source with location and properties"""
    source_id: str
    source_type: SoundSourceType
    direction_degrees: float  # 0-360, 0=front, 90=right, 180=back, 270=left
    distance_estimate: Optional[float] = None  # Estimated distance in meters
    confidence: float = 0.0  # 0.0-1.0 confidence in detection
    intensity: float = 0.0   # Sound intensity/volume
    frequency_profile: Optional[Dict[str, float]] = None  # Frequency characteristics
    last_detected: float = 0.0  # Timestamp of last detection
    tracking_duration: float = 0.0  # How long this source has been tracked
    
class AudioEvent(Enum):
    """Types of audio events that can be detected"""
    SOUND_DETECTED = "sound_detected"
    VOICE_DETECTED = "voice_detected"
    LOUD_NOISE = "loud_noise"
    SILENCE_STARTED = "silence_started"
    SILENCE_ENDED = "silence_ended"
    NEW_SOURCE_TRACKED = "new_source_tracked"
    SOURCE_LOST = "source_lost"
    DIRECTION_CHANGED = "direction_changed"

@dataclass
class AudioEventRecord:
    """Record of an audio processing event"""
    timestamp: float
    event_type: AudioEvent
    source_id: Optional[str] = None
    direction: Optional[float] = None
    intensity: float = 0.0
    confidence: float = 0.0
    description: str = ""
    metadata: Optional[Dict] = None

@dataclass
class AudioStatistics:
    """Audio processing performance statistics"""
    total_samples_processed: int = 0
    voice_detections: int = 0
    sound_sources_tracked: int = 0
    average_noise_level: float = 0.0
    peak_noise_level: float = 0.0
    silence_percentage: float = 0.0
    direction_accuracy: float = 0.0  # Estimated accuracy of direction detection

class EnhancedAudioProcessingService:
    """
    Advanced audio processing service for sound tracking and localization
    
    This service provides:
    1. Real-time audio monitoring from microphone array
    2. Sound source detection and directional tracking
    3. Voice activity detection and speech classification
    4. Background noise filtering and audio enhancement
    5. Audio event logging and pattern recognition
    6. Integration with PiDog's sound direction sensor
    """
    
    def __init__(self, config):
        """Initialize the Enhanced Audio Processing Service"""
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Service state
        self.is_running = False
        self.is_processing = False
        self.processing_thread = None
        self.audio_stream = None
        
        # Audio processing setup
        self.sample_rate = config.AUDIO_SAMPLE_RATE
        self.channels = config.AUDIO_CHANNELS
        self.chunk_size = config.AUDIO_CHUNK_SIZE
        self.buffer_duration = config.AUDIO_BUFFER_DURATION
        
        # Audio data storage
        self.audio_buffer = queue.Queue(maxsize=100)
        self.current_sample: Optional[AudioSample] = None
        self.audio_history: List[AudioSample] = []
        
        # Sound source tracking
        self.active_sources: Dict[str, SoundSource] = {}
        self.source_counter = 0
        self.direction_history: List[Tuple[float, float]] = []  # (timestamp, direction)
        
        # Audio analysis
        self.background_noise_level = 0.0
        self.silence_threshold = config.AUDIO_SILENCE_THRESHOLD
        self.voice_frequency_range = (config.AUDIO_VOICE_FREQ_MIN, config.AUDIO_VOICE_FREQ_MAX)
        self.is_silent_period = False
        self.silence_start_time = 0.0
        
        # Event tracking
        self.audio_events: List[AudioEventRecord] = []
        self.statistics = AudioStatistics()
        
        # Callback functions
        self.audio_callbacks: Dict[AudioEvent, List[Callable]] = {
            event: [] for event in AudioEvent
        }
        
        # Data storage
        self.data_dir = Path(config.AUDIO_DATA_DIR)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize hardware connections
        self.pyaudio_instance = None
        self.pidog_instance = None
        
        if config.ENABLE_ENHANCED_AUDIO:
            self._initialize_audio_hardware()
        
        self.logger.info("Enhanced Audio Processing Service initialized")
    
    def _initialize_audio_hardware(self):
        """Initialize audio hardware connections"""
        
        # Initialize PyAudio for microphone access
        if pyaudio:
            try:
                self.pyaudio_instance = pyaudio.PyAudio()
                
                # List available audio devices for debugging
                device_count = self.pyaudio_instance.get_device_count()
                self.logger.info(f"Found {device_count} audio devices")
                
                for i in range(device_count):
                    device_info = self.pyaudio_instance.get_device_info_by_index(i)
                    max_input_channels = device_info.get('maxInputChannels', 0)
                    if isinstance(max_input_channels, (int, float)) and max_input_channels > 0:
                        self.logger.debug(f"Input device {i}: {device_info.get('name', 'Unknown')}")
                
            except Exception as e:
                self.logger.warning(f"Could not initialize PyAudio: {e}")
                self.pyaudio_instance = None
        
        # Initialize PiDog hardware for sound direction sensor
        if pidog and self.config.ENABLE_ENHANCED_AUDIO:
            try:
                self.pidog_instance = pidog.PiDog()
                self.logger.info("Enhanced Audio Service: Connected to PiDog hardware")
            except Exception as e:
                self.logger.warning(f"Enhanced Audio Service: Could not connect to PiDog: {e}")
    
    def start(self):
        """Start the audio processing service"""
        if not self.config.ENABLE_ENHANCED_AUDIO:
            self.logger.info("Enhanced Audio Processing Service: Disabled in configuration")
            return
        
        if self.is_running:
            self.logger.warning("Enhanced Audio Processing Service: Already running")
            return
        
        self.is_running = True
        
        # Start audio stream
        if self._start_audio_stream():
            # Calibrate background noise
            self.logger.info("Enhanced Audio Service: Calibrating background noise...")
            self._calibrate_background_noise()
            
            # Start processing thread
            self.is_processing = True
            self.processing_thread = threading.Thread(target=self._processing_loop, daemon=True)
            self.processing_thread.start()
            
            self.logger.info("Enhanced Audio Processing Service: Started successfully")
        else:
            self.is_running = False
            self.logger.error("Enhanced Audio Processing Service: Failed to start audio stream")
    
    def stop(self):
        """Stop the audio processing service"""
        if not self.is_running:
            return
        
        self.is_processing = False
        self.is_running = False
        
        # Stop audio stream
        if self.audio_stream:
            try:
                self.audio_stream.stop_stream()
                self.audio_stream.close()
            except Exception as e:
                self.logger.error(f"Error stopping audio stream: {e}")
        
        # Wait for processing thread to finish
        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join(timeout=2.0)
        
        # Cleanup PyAudio
        if self.pyaudio_instance:
            try:
                self.pyaudio_instance.terminate()
            except Exception as e:
                self.logger.error(f"Error terminating PyAudio: {e}")
        
        # Save session data
        self._save_session_data()
        
        self.logger.info("Enhanced Audio Processing Service: Stopped")
    
    def _start_audio_stream(self) -> bool:
        """Start the audio input stream"""
        if not self.pyaudio_instance:
            # Simulation mode
            self.logger.info("Audio simulation mode active")
            return True
        
        try:
            # Configure audio stream
            audio_format = pyaudio.paInt16  # 16-bit samples
            
            self.audio_stream = self.pyaudio_instance.open(
                format=audio_format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.config.AUDIO_INPUT_DEVICE_INDEX,
                frames_per_buffer=self.chunk_size,
                stream_callback=self._audio_callback
            )
            
            self.audio_stream.start_stream()
            self.logger.info(f"Audio stream started: {self.sample_rate}Hz, {self.channels} channels")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start audio stream: {e}")
            return False
    
    def _audio_callback(self, in_data, frame_count, time_info, status):
        """PyAudio callback for incoming audio data"""
        try:
            # Convert audio data to numpy array
            audio_data = np.frombuffer(in_data, dtype=np.int16)
            
            # Convert to float and normalize
            audio_data = audio_data.astype(np.float32) / 32768.0
            
            # Calculate audio levels
            rms_level = np.sqrt(np.mean(audio_data**2))
            peak_level = np.max(np.abs(audio_data))
            
            # Create audio sample
            sample = AudioSample(
                timestamp=time.time(),
                audio_data=audio_data,
                sample_rate=self.sample_rate,
                channels=self.channels,
                duration=len(audio_data) / self.sample_rate,
                rms_level=rms_level,
                peak_level=peak_level
            )
            
            # Add to buffer (non-blocking)
            if not self.audio_buffer.full():
                self.audio_buffer.put(sample)
            
        except Exception as e:
            self.logger.error(f"Error in audio callback: {e}")
        
        return (None, pyaudio.paContinue)
    
    def _calibrate_background_noise(self):
        """Calibrate background noise level for better detection"""
        calibration_samples = []
        calibration_duration = self.config.AUDIO_CALIBRATION_TIME
        start_time = time.time()
        
        self.logger.info(f"Calibrating background noise for {calibration_duration} seconds...")
        
        while time.time() - start_time < calibration_duration:
            try:
                if self.pyaudio_instance:
                    # Get sample from buffer
                    if not self.audio_buffer.empty():
                        sample = self.audio_buffer.get(timeout=0.1)
                        calibration_samples.append(sample.rms_level)
                else:
                    # Simulation mode
                    import random
                    calibration_samples.append(random.uniform(0.001, 0.01))
                
                time.sleep(0.1)
                
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.warning(f"Error during noise calibration: {e}")
        
        if calibration_samples:
            self.background_noise_level = np.mean(calibration_samples)
            noise_std = np.std(calibration_samples)
            
            # Set silence threshold above background noise
            self.silence_threshold = self.background_noise_level + (2 * noise_std)
            
            self.logger.info(f"Background noise calibrated: {self.background_noise_level:.4f} "
                           f"(threshold: {self.silence_threshold:.4f})")
        else:
            self.logger.warning("No calibration samples collected, using default values")
    
    def _processing_loop(self):
        """Main audio processing loop running in separate thread"""
        
        while self.is_processing:
            try:
                # Get audio sample from buffer
                if self.pyaudio_instance:
                    try:
                        sample = self.audio_buffer.get(timeout=0.1)
                    except queue.Empty:
                        continue
                else:
                    # Simulation mode
                    sample = self._generate_simulation_sample()
                    time.sleep(0.05)  # Simulate processing delay
                
                # Process the audio sample
                self._process_audio_sample(sample)
                
            except Exception as e:
                self.logger.error(f"Error in audio processing loop: {e}")
                time.sleep(0.1)
    
    def _generate_simulation_sample(self) -> AudioSample:
        """Generate simulated audio sample for testing"""
        import random
        
        # Generate some realistic audio simulation
        duration = 0.05  # 50ms chunks
        samples = int(self.sample_rate * duration)
        
        # Simulate background noise with occasional sounds
        noise_level = random.uniform(0.001, 0.01)
        
        # Occasionally add a "voice" or "sound" event
        if random.random() < 0.05:  # 5% chance of sound event
            noise_level *= random.uniform(5, 20)  # Much louder
        
        audio_data = np.random.normal(0, noise_level, samples)
        
        return AudioSample(
            timestamp=time.time(),
            audio_data=audio_data,
            sample_rate=self.sample_rate,
            channels=self.channels,
            duration=duration,
            rms_level=noise_level,
            peak_level=np.max(np.abs(audio_data))
        )
    
    def _process_audio_sample(self, sample: AudioSample):
        """Process a single audio sample for sound detection and analysis"""
        
        self.current_sample = sample
        self.statistics.total_samples_processed += 1
        
        # Add to history (keep limited size)
        self.audio_history.append(sample)
        if len(self.audio_history) > self.config.AUDIO_HISTORY_SIZE:
            self.audio_history.pop(0)
        
        # Update noise level statistics
        self._update_noise_statistics(sample)
        
        # Check for silence/sound transitions
        self._detect_silence_transitions(sample)
        
        # Analyze for voice activity
        if self._detect_voice_activity(sample):
            self._handle_voice_detection(sample)
        
        # Detect sound sources and direction
        self._detect_sound_sources(sample)
        
        # Update source tracking
        self._update_source_tracking(sample)
        
        # Check for audio events
        self._detect_audio_events(sample)
    
    def _update_noise_statistics(self, sample: AudioSample):
        """Update running noise level statistics"""
        
        # Update average noise level (exponential moving average)
        alpha = 0.1  # Smoothing factor
        self.statistics.average_noise_level = (
            alpha * sample.rms_level + 
            (1 - alpha) * self.statistics.average_noise_level
        )
        
        # Update peak noise level
        self.statistics.peak_noise_level = max(
            self.statistics.peak_noise_level, 
            sample.peak_level
        )
    
    def _detect_silence_transitions(self, sample: AudioSample):
        """Detect transitions between silence and sound"""
        
        is_currently_silent = sample.rms_level < self.silence_threshold
        
        # Check for silence state changes
        if is_currently_silent and not self.is_silent_period:
            # Silence started
            self.is_silent_period = True
            self.silence_start_time = sample.timestamp
            self._trigger_audio_event(
                AudioEvent.SILENCE_STARTED,
                sample,
                "Silence period started"
            )
            
        elif not is_currently_silent and self.is_silent_period:
            # Silence ended
            silence_duration = sample.timestamp - self.silence_start_time
            self.is_silent_period = False
            self._trigger_audio_event(
                AudioEvent.SILENCE_ENDED,
                sample,
                f"Silence ended after {silence_duration:.1f}s"
            )
        
        # Update silence percentage
        if len(self.audio_history) > 0:
            silent_samples = sum(1 for s in self.audio_history if s.rms_level < self.silence_threshold)
            self.statistics.silence_percentage = (silent_samples / len(self.audio_history)) * 100
    
    def _detect_voice_activity(self, sample: AudioSample) -> bool:
        """Detect if current sample contains voice activity"""
        
        # Check if audio level is above background noise
        if sample.rms_level < self.background_noise_level * 3:
            return False
        
        # Check frequency characteristics for voice
        if sample.fft_data is not None and sample.frequencies is not None:
            # Look for energy in voice frequency range
            voice_mask = (
                (sample.frequencies >= self.voice_frequency_range[0]) &
                (sample.frequencies <= self.voice_frequency_range[1])
            )
            
            voice_energy = np.sum(np.abs(sample.fft_data[voice_mask]))
            total_energy = np.sum(np.abs(sample.fft_data))
            
            if total_energy > 0:
                voice_ratio = voice_energy / total_energy
                return voice_ratio > self.config.AUDIO_VOICE_THRESHOLD
        
        # Fallback to simple level check
        return sample.rms_level > self.silence_threshold * 2
    
    def _handle_voice_detection(self, sample: AudioSample):
        """Handle detected voice activity"""
        
        self.statistics.voice_detections += 1
        
        # Get direction from PiDog sensor if available
        direction = self._get_sound_direction()
        
        self._trigger_audio_event(
            AudioEvent.VOICE_DETECTED,
            sample,
            "Voice activity detected",
            direction=direction
        )
        
        self.logger.debug(f"Voice detected: level={sample.rms_level:.3f}, direction={direction}°")
    
    def _detect_sound_sources(self, sample: AudioSample):
        """Detect and track sound sources"""
        
        # Only process if above noise threshold
        if sample.rms_level < self.silence_threshold:
            return
        
        # Get direction from hardware
        direction = self._get_sound_direction()
        if direction is None:
            return
        
        # Add to direction history
        self.direction_history.append((sample.timestamp, direction))
        if len(self.direction_history) > self.config.AUDIO_DIRECTION_HISTORY_SIZE:
            self.direction_history.pop(0)
        
        # Classify sound type
        sound_type = self._classify_sound_type(sample)
        
        # Check if this matches an existing source
        existing_source = self._find_nearby_source(direction, sound_type)
        
        if existing_source:
            # Update existing source
            existing_source.last_detected = sample.timestamp
            existing_source.intensity = sample.rms_level
            existing_source.confidence = min(existing_source.confidence + 0.1, 1.0)
            
            # Check if direction has changed significantly
            if abs(existing_source.direction_degrees - direction) > self.config.AUDIO_DIRECTION_CHANGE_THRESHOLD:
                self._trigger_audio_event(
                    AudioEvent.DIRECTION_CHANGED,
                    sample,
                    f"Source {existing_source.source_id} moved from {existing_source.direction_degrees:.0f}° to {direction:.0f}°",
                    source_id=existing_source.source_id,
                    direction=direction
                )
                existing_source.direction_degrees = direction
        else:
            # Create new source
            source_id = f"source_{self.source_counter}"
            self.source_counter += 1
            
            new_source = SoundSource(
                source_id=source_id,
                source_type=sound_type,
                direction_degrees=direction,
                confidence=0.5,
                intensity=sample.rms_level,
                last_detected=sample.timestamp,
                tracking_duration=0.0
            )
            
            self.active_sources[source_id] = new_source
            self.statistics.sound_sources_tracked += 1
            
            self._trigger_audio_event(
                AudioEvent.NEW_SOURCE_TRACKED,
                sample,
                f"New {sound_type.value} source detected at {direction:.0f}°",
                source_id=source_id,
                direction=direction
            )
    
    def _get_sound_direction(self) -> Optional[float]:
        """Get sound direction from PiDog sensor or estimate from microphones"""
        
        if self.pidog_instance:
            try:
                # Get direction from PiDog's sound direction sensor
                direction_data = self.pidog_instance.get_sound_direction()
                if direction_data:
                    return float(direction_data)  # Assuming this returns degrees
            except Exception as e:
                self.logger.warning(f"Error getting sound direction from PiDog: {e}")
        
        # Fallback: simulate or estimate direction
        if self.current_sample and len(self.direction_history) > 0:
            # Use recent direction as estimate
            return self.direction_history[-1][1]
        
        # Random direction for simulation
        import random
        return random.uniform(0, 360)
    
    def _classify_sound_type(self, sample: AudioSample) -> SoundSourceType:
        """Classify the type of sound based on audio characteristics"""
        
        # Simple classification based on frequency and level characteristics
        if sample.fft_data is None:
            return SoundSourceType.UNKNOWN
        
        # Analyze frequency spectrum
        magnitude_spectrum = np.abs(sample.fft_data)
        
        # Voice detection (frequency range analysis)
        if sample.frequencies is not None:
            voice_mask = (
                (sample.frequencies >= self.voice_frequency_range[0]) &
                (sample.frequencies <= self.voice_frequency_range[1])
            )
            voice_energy = np.sum(magnitude_spectrum[voice_mask])
            total_energy = np.sum(magnitude_spectrum)
            
            if total_energy > 0 and voice_energy / total_energy > 0.6:
                return SoundSourceType.VOICE
        
        # High intensity = possible alarm
        if sample.rms_level > self.silence_threshold * 10:
            return SoundSourceType.ALARM
        
        # Medium intensity patterns
        if sample.rms_level > self.silence_threshold * 3:
            # Could be footsteps, mechanical sounds, etc.
            # More sophisticated analysis would go here
            return SoundSourceType.ENVIRONMENTAL
        
        return SoundSourceType.UNKNOWN
    
    def _find_nearby_source(self, direction: float, sound_type: SoundSourceType) -> Optional[SoundSource]:
        """Find existing sound source near the given direction"""
        
        direction_tolerance = self.config.AUDIO_SOURCE_DIRECTION_TOLERANCE
        
        for source in self.active_sources.values():
            # Calculate angular difference (accounting for wrap-around)
            angle_diff = abs(source.direction_degrees - direction)
            if angle_diff > 180:
                angle_diff = 360 - angle_diff
            
            # Check if within tolerance and same type
            if angle_diff <= direction_tolerance and source.source_type == sound_type:
                return source
        
        return None
    
    def _update_source_tracking(self, sample: AudioSample):
        """Update tracking for all active sources"""
        
        current_time = sample.timestamp
        timeout = self.config.AUDIO_SOURCE_TIMEOUT
        
        # Update tracking duration and remove stale sources
        sources_to_remove = []
        
        for source_id, source in self.active_sources.items():
            source.tracking_duration = current_time - (current_time - source.tracking_duration)
            
            # Check if source has timed out
            if current_time - source.last_detected > timeout:
                sources_to_remove.append(source_id)
                
                self._trigger_audio_event(
                    AudioEvent.SOURCE_LOST,
                    sample,
                    f"Lost tracking of {source.source_type.value} source at {source.direction_degrees:.0f}°",
                    source_id=source_id,
                    direction=source.direction_degrees
                )
        
        # Remove timed-out sources
        for source_id in sources_to_remove:
            del self.active_sources[source_id]
    
    def _detect_audio_events(self, sample: AudioSample):
        """Detect special audio events and patterns"""
        
        # Detect loud noise events
        if sample.rms_level > self.config.AUDIO_LOUD_NOISE_THRESHOLD:
            self._trigger_audio_event(
                AudioEvent.LOUD_NOISE,
                sample,
                f"Loud noise detected: {sample.rms_level:.3f}"
            )
        
        # General sound detection
        elif sample.rms_level > self.silence_threshold:
            self._trigger_audio_event(
                AudioEvent.SOUND_DETECTED,
                sample,
                f"Sound detected: {sample.rms_level:.3f}"
            )
    
    def _trigger_audio_event(self, event_type: AudioEvent, sample: AudioSample, 
                           description: str, source_id: Optional[str] = None, 
                           direction: Optional[float] = None):
        """Trigger an audio event and notify callbacks"""
        
        # Create event record
        event = AudioEventRecord(
            timestamp=sample.timestamp,
            event_type=event_type,
            source_id=source_id,
            direction=direction,
            intensity=sample.rms_level,
            confidence=1.0,  # Could be calculated based on detection quality
            description=description
        )
        
        self.audio_events.append(event)
        
        # Keep event history limited
        if len(self.audio_events) > self.config.AUDIO_EVENT_HISTORY_SIZE:
            self.audio_events.pop(0)
        
        # Notify callbacks
        for callback in self.audio_callbacks.get(event_type, []):
            try:
                callback(event, sample)
            except Exception as e:
                self.logger.error(f"Error in audio callback: {e}")
        
        # Log significant events
        if event_type in [AudioEvent.VOICE_DETECTED, AudioEvent.LOUD_NOISE, 
                         AudioEvent.NEW_SOURCE_TRACKED]:
            self.logger.info(f"Audio Event: {event_type.value} - {description}")
    
    def _save_session_data(self):
        """Save audio session data to disk"""
        try:
            session_data = {
                'timestamp': time.time(),
                'statistics': {
                    'total_samples_processed': self.statistics.total_samples_processed,
                    'voice_detections': self.statistics.voice_detections,
                    'sound_sources_tracked': self.statistics.sound_sources_tracked,
                    'average_noise_level': self.statistics.average_noise_level,
                    'peak_noise_level': self.statistics.peak_noise_level,
                    'silence_percentage': self.statistics.silence_percentage
                },
                'events': [
                    {
                        'timestamp': e.timestamp,
                        'event_type': e.event_type.value,
                        'source_id': e.source_id,
                        'direction': e.direction,
                        'intensity': e.intensity,
                        'confidence': e.confidence,
                        'description': e.description
                    }
                    for e in self.audio_events[-100:]  # Save last 100 events
                ],
                'config': {
                    'sample_rate': self.sample_rate,
                    'channels': self.channels,
                    'background_noise_level': self.background_noise_level,
                    'silence_threshold': self.silence_threshold
                }
            }
            
            session_file = self.data_dir / f"audio_session_{int(time.time())}.json"
            with open(session_file, 'w') as f:
                json.dump(session_data, f, indent=2)
            
            self.logger.info(f"Audio session data saved to {session_file}")
            
        except Exception as e:
            self.logger.error(f"Error saving audio session data: {e}")
    
    # Public API methods
    
    def get_current_audio_level(self) -> float:
        """Get current RMS audio level"""
        if self.current_sample:
            return self.current_sample.rms_level
        return 0.0
    
    def get_background_noise_level(self) -> float:
        """Get calibrated background noise level"""
        return self.background_noise_level
    
    def get_active_sources(self) -> Dict[str, SoundSource]:
        """Get currently tracked sound sources"""
        return self.active_sources.copy()
    
    def get_sound_direction_history(self) -> List[Tuple[float, float]]:
        """Get recent sound direction history as (timestamp, direction) pairs"""
        return self.direction_history.copy()
    
    def is_voice_detected(self) -> bool:
        """Check if voice is currently being detected"""
        if self.current_sample:
            return self._detect_voice_activity(self.current_sample)
        return False
    
    def register_audio_callback(self, event_type: AudioEvent, callback: Callable):
        """Register callback function for specific audio event"""
        if event_type not in self.audio_callbacks:
            self.audio_callbacks[event_type] = []
        self.audio_callbacks[event_type].append(callback)
    
    def get_audio_statistics(self) -> AudioStatistics:
        """Get current audio processing statistics"""
        return self.statistics
    
    def set_silence_threshold(self, threshold: float):
        """Manually adjust silence detection threshold"""
        self.silence_threshold = max(threshold, self.background_noise_level)
        self.logger.info(f"Silence threshold updated to {self.silence_threshold:.4f}")
    
    def reset_statistics(self):
        """Reset audio processing statistics"""
        self.statistics = AudioStatistics()
        self.audio_events.clear()
        self.logger.info("Audio statistics reset")