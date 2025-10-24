#!/usr/bin/env python3
"""
Integration Test for New HoundMind Services
==========================================

This script tests the integration of the three new AI services:
1. Face Recognition Service
2. Dynamic Balance Service  
3. Enhanced Audio Processing Service

It validates that they can be initialized, configured, and integrated
with the PackMind orchestrator without errors.

Run with: python scripts/test_service_integration.py
"""

import sys
import os
import time
import logging

# Add the project root to the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("integration_test")

def test_service_imports():
    """Test that all service imports work correctly"""
    logger.info("Testing service imports...")
    
    try:
        from packmind.services.face_recognition_service import FaceRecognitionService
        logger.info("✓ Face Recognition Service import successful")
    except ImportError as e:
        logger.error(f"✗ Face Recognition Service import failed: {e}")
        return False
    
    try:
        from packmind.services.dynamic_balance_service import DynamicBalanceService
        logger.info("✓ Dynamic Balance Service import successful")
    except ImportError as e:
        logger.error(f"✗ Dynamic Balance Service import failed: {e}")
        return False
    
    try:
        from packmind.services.enhanced_audio_processing_service import EnhancedAudioProcessingService
        logger.info("✓ Enhanced Audio Processing Service import successful")
    except ImportError as e:
        logger.error(f"✗ Enhanced Audio Processing Service import failed: {e}")
        return False
    
    return True

def test_configuration_loading():
    """Test that configuration loading works with new services"""
    logger.info("Testing configuration loading...")
    
    try:
        from packmind.packmind_config import load_config
        
        # Test different configuration presets
        configs_to_test = ["simple", "advanced", "indoor_pet", "explorer"]
        
        for config_name in configs_to_test:
            try:
                config = load_config(config_name)
                
                # Check that new service flags exist
                assert hasattr(config, 'ENABLE_FACE_RECOGNITION'), f"Missing ENABLE_FACE_RECOGNITION in {config_name}"
                assert hasattr(config, 'ENABLE_DYNAMIC_BALANCE'), f"Missing ENABLE_DYNAMIC_BALANCE in {config_name}"
                assert hasattr(config, 'ENABLE_ENHANCED_AUDIO'), f"Missing ENABLE_ENHANCED_AUDIO in {config_name}"
                
                # Check that configuration parameters exist
                if config.ENABLE_FACE_RECOGNITION:
                    assert hasattr(config, 'FACE_RECOGNITION_THRESHOLD'), f"Missing face recognition params in {config_name}"
                
                if config.ENABLE_DYNAMIC_BALANCE:
                    assert hasattr(config, 'BALANCE_SAMPLE_RATE'), f"Missing balance params in {config_name}"
                
                if config.ENABLE_ENHANCED_AUDIO:
                    assert hasattr(config, 'AUDIO_SAMPLE_RATE'), f"Missing audio params in {config_name}"
                
                logger.info(f"✓ Configuration '{config_name}' loaded successfully")
                
            except Exception as e:
                logger.error(f"✗ Configuration '{config_name}' failed to load: {e}")
                return False
        
        return True
        
    except ImportError as e:
        logger.error(f"✗ Configuration import failed: {e}")
        return False

def test_service_initialization():
    """Test that services can be initialized without errors"""
    logger.info("Testing service initialization...")
    
    try:
        from packmind.packmind_config import load_config
        from packmind.services.face_recognition_service import FaceRecognitionService
        from packmind.services.dynamic_balance_service import DynamicBalanceService
        from packmind.services.enhanced_audio_processing_service import EnhancedAudioProcessingService
        
        # Load test configuration
        config = load_config("simple")  # Use simple config for testing
        
        # Test Face Recognition Service
        try:
            face_service = FaceRecognitionService(config)
            logger.info("✓ Face Recognition Service initialized")
        except Exception as e:
            logger.error(f"✗ Face Recognition Service initialization failed: {e}")
            return False
        
        # Test Dynamic Balance Service
        try:
            balance_service = DynamicBalanceService(config)
            logger.info("✓ Dynamic Balance Service initialized")
        except Exception as e:
            logger.error(f"✗ Dynamic Balance Service initialization failed: {e}")
            return False
        
        # Test Enhanced Audio Processing Service
        try:
            audio_service = EnhancedAudioProcessingService(config)
            logger.info("✓ Enhanced Audio Processing Service initialized")
        except Exception as e:
            logger.error(f"✗ Enhanced Audio Processing Service initialization failed: {e}")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Service initialization test failed: {e}")
        return False

def test_orchestrator_integration():
    """Test that the orchestrator can integrate with new services"""
    logger.info("Testing orchestrator integration...")
    
    try:
        from packmind.orchestrator import Orchestrator
        
        # Create orchestrator with simple config (services disabled for testing)
        orchestrator = Orchestrator("simple")
        
        # Check that service attributes exist
        assert hasattr(orchestrator, 'face_recognition_service'), "Missing face_recognition_service attribute"
        assert hasattr(orchestrator, 'dynamic_balance_service'), "Missing dynamic_balance_service attribute"
        assert hasattr(orchestrator, 'enhanced_audio_service'), "Missing enhanced_audio_service attribute"
        
        # Check that integration method exists
        assert hasattr(orchestrator, '_check_service_integration'), "Missing _check_service_integration method"
        
        logger.info("✓ Orchestrator integration successful")
        return True
        
    except Exception as e:
        logger.error(f"✗ Orchestrator integration failed: {e}")
        return False

def test_service_api():
    """Test that service APIs work as expected"""
    logger.info("Testing service APIs...")
    
    try:
        from packmind.packmind_config import load_config
        from packmind.services.face_recognition_service import FaceRecognitionService
        from packmind.services.dynamic_balance_service import DynamicBalanceService
        from packmind.services.enhanced_audio_processing_service import EnhancedAudioProcessingService
        
        config = load_config("simple")
        
        # Test Face Recognition Service API
        face_service = FaceRecognitionService(config)
        assert hasattr(face_service, 'start'), "Missing start method"
        assert hasattr(face_service, 'stop'), "Missing stop method"
        assert hasattr(face_service, 'detect_and_recognize'), "Missing detect_and_recognize method"
        logger.info("✓ Face Recognition Service API validated")
        
        # Test Dynamic Balance Service API
        balance_service = DynamicBalanceService(config)
        assert hasattr(balance_service, 'start'), "Missing start method"
        assert hasattr(balance_service, 'stop'), "Missing stop method"
        assert hasattr(balance_service, 'get_current_balance_state'), "Missing get_current_balance_state method"
        logger.info("✓ Dynamic Balance Service API validated")
        
        # Test Enhanced Audio Processing Service API
        audio_service = EnhancedAudioProcessingService(config)
        assert hasattr(audio_service, 'start'), "Missing start method"
        assert hasattr(audio_service, 'stop'), "Missing stop method"
        assert hasattr(audio_service, 'get_current_audio_level'), "Missing get_current_audio_level method"
        logger.info("✓ Enhanced Audio Processing Service API validated")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Service API test failed: {e}")
        return False

def main():
    """Run all integration tests"""
    logger.info("🚀 Starting HoundMind Service Integration Tests")
    logger.info("=" * 50)
    
    tests = [
        ("Service Imports", test_service_imports),
        ("Configuration Loading", test_configuration_loading),
        ("Service Initialization", test_service_initialization),
        ("Orchestrator Integration", test_orchestrator_integration),
        ("Service APIs", test_service_api)
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        logger.info(f"\n🧪 Running {test_name}...")
        try:
            if test_func():
                passed += 1
                logger.info(f"✅ {test_name} PASSED")
            else:
                failed += 1
                logger.error(f"❌ {test_name} FAILED")
        except Exception as e:
            failed += 1
            logger.error(f"❌ {test_name} FAILED with exception: {e}")
    
    # Final report
    logger.info("\n" + "=" * 50)
    logger.info(f"📊 TEST RESULTS: {passed} passed, {failed} failed")
    
    if failed == 0:
        logger.info("🎉 ALL TESTS PASSED! Services are fully integrated.")
        return True
    else:
        logger.error(f"💥 {failed} tests failed. Please check the integration.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)