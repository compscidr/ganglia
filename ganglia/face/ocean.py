"""
Ocean wave face visualization for Kai.
Displays animated ocean waves that react when speaking.
"""

import pygame
import math
import time
import random
from pathlib import Path
from typing import Optional


# Ocean color palette
COLORS = {
    'deep': (10, 30, 60),       # Deep ocean background
    'wave1': (20, 80, 140),     # Primary wave
    'wave2': (40, 120, 180),    # Secondary wave  
    'wave3': (70, 160, 210),    # Tertiary wave
    'foam': (180, 220, 240),    # Wave foam/highlights
    'glow': (100, 200, 255),    # Speaking glow
}


class Wave:
    """A single animated wave layer."""
    
    def __init__(
        self,
        amplitude: float,
        frequency: float,
        speed: float,
        color: tuple,
        y_offset: float,
        phase: float = 0,
    ):
        self.base_amplitude = amplitude
        self.amplitude = amplitude
        self.frequency = frequency
        self.speed = speed
        self.color = color
        self.y_offset = y_offset
        self.phase = phase
        self.time = random.random() * 100  # Random start position
        
    def update(self, dt: float, energy: float = 0):
        """Update wave state."""
        # Speed up waves when speaking
        speed_multiplier = 1 + energy * 3
        self.time += dt * self.speed * speed_multiplier
        # Increase amplitude when speaking
        target_amp = self.base_amplitude * (1 + energy * 2)
        self.amplitude += (target_amp - self.amplitude) * 0.1
        
    def get_y(self, x: float, width: float) -> float:
        """Get wave Y position at X coordinate."""
        normalized_x = x / width * math.pi * 2 * self.frequency
        return math.sin(normalized_x + self.time + self.phase) * self.amplitude


class OceanFace:
    """
    Kai's ocean wave face visualization.
    
    Shows animated waves that intensify when speaking.
    """
    
    def __init__(
        self,
        width: int = 800,
        height: int = 400,
        title: str = "🌊 Kai",
    ):
        self.width = width
        self.height = height
        self.title = title
        self.speaking_file = Path.home() / ".clawdbot" / "ganglia-speaking"
        self.level_file = Path.home() / ".clawdbot" / "ganglia-audio-level"
        
        # Wave layers (back to front)
        self.waves = [
            Wave(amplitude=30, frequency=1.5, speed=0.8, color=COLORS['wave1'], y_offset=0.7, phase=0),
            Wave(amplitude=25, frequency=2.0, speed=1.2, color=COLORS['wave2'], y_offset=0.6, phase=1),
            Wave(amplitude=20, frequency=2.5, speed=1.6, color=COLORS['wave3'], y_offset=0.5, phase=2),
            Wave(amplitude=15, frequency=3.0, speed=2.0, color=COLORS['foam'], y_offset=0.45, phase=3),
        ]
        
        # State
        self.energy = 0  # 0-1, how much we're speaking
        self.target_energy = 0
        self.glow_phase = 0
        
        # Particles for extra life
        self.particles = []
        
        # Cache speaking state to avoid file check every frame
        self._speaking_cache = 0.0
        self._speaking_check_timer = 0
        
        # Stop flag for clean shutdown
        self._running = False
        
    def get_audio_level(self, dt: float = 0) -> float:
        """Get current audio level (0-1) from TTS playback."""
        self._speaking_check_timer += dt
        if self._speaking_check_timer >= 0.05:  # Check every 50ms
            self._speaking_check_timer = 0
            try:
                # Try audio level file first (more granular)
                if self.level_file.exists():
                    level_str = self.level_file.read_text().strip()
                    if level_str:
                        self._speaking_cache = float(level_str)
                        return self._speaking_cache
                # Fall back to binary speaking flag
                if self.speaking_file.exists():
                    self._speaking_cache = 1.0
                else:
                    self._speaking_cache = 0.0
            except Exception:
                pass
        return self._speaking_cache if isinstance(self._speaking_cache, float) else (1.0 if self._speaking_cache else 0.0)
    
    def update(self, dt: float):
        """Update animation state."""
        # Update energy based on audio level (0-1, follows actual sound)
        self.target_energy = self.get_audio_level(dt)
        self.energy += (self.target_energy - self.energy) * 0.3  # Fast response to audio
        
        # Update waves
        for wave in self.waves:
            wave.update(dt, self.energy)
        
        # Update glow
        self.glow_phase += dt * 3
        
        # Spawn more particles when speaking
        if self.energy > 0.2 and random.random() < self.energy * 0.5:
            self.particles.append({
                'x': random.randint(0, self.width),
                'y': self.height * 0.5,
                'vx': random.uniform(-20, 20),
                'vy': random.uniform(-50, -100),
                'life': 1.0,
                'size': random.uniform(2, 6),
            })
        
        # Update particles
        for p in self.particles:
            p['x'] += p['vx'] * dt
            p['y'] += p['vy'] * dt
            p['vy'] += 100 * dt  # Gravity
            p['life'] -= dt * 0.5
        
        # Remove dead particles
        self.particles = [p for p in self.particles if p['life'] > 0]
    
    def draw(self, screen):
        """Draw the ocean visualization."""
        # Background gradient
        for y in range(self.height):
            t = y / self.height
            r = int(COLORS['deep'][0] * (1 - t * 0.5))
            g = int(COLORS['deep'][1] * (1 - t * 0.3))
            b = int(COLORS['deep'][2] * (1 - t * 0.2))
            pygame.draw.line(screen, (r, g, b), (0, y), (self.width, y))
        
        # Speaking glow effect
        if self.energy > 0.1:
            glow_intensity = int(self.energy * 50 * (0.7 + 0.3 * math.sin(self.glow_phase)))
            glow_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            pygame.draw.ellipse(
                glow_surface,
                (*COLORS['glow'], glow_intensity),
                (self.width // 4, self.height // 4, self.width // 2, self.height // 2)
            )
            screen.blit(glow_surface, (0, 0))
        
        # Draw waves (back to front)
        for wave in self.waves:
            points = []
            base_y = self.height * wave.y_offset
            
            # Top edge of wave
            for x in range(0, self.width + 10, 5):
                y = base_y + wave.get_y(x, self.width)
                points.append((x, y))
            
            # Bottom corners to close polygon
            points.append((self.width, self.height))
            points.append((0, self.height))
            
            # Draw filled polygon
            if len(points) > 2:
                pygame.draw.polygon(screen, wave.color, points)
        
        # Draw particles
        for p in self.particles:
            alpha = int(p['life'] * 255)
            color = (*COLORS['foam'], alpha)
            pygame.draw.circle(
                screen,
                COLORS['foam'],
                (int(p['x']), int(p['y'])),
                int(p['size'] * p['life'])
            )
        
        # Draw a simple glow circle when speaking instead of text (font has issues)
        if self.energy > 0.5:
            glow_size = int(30 + self.energy * 20)
            glow_alpha = int(self.energy * 200)
            center = (self.width // 2, self.height // 3)
            pygame.draw.circle(screen, COLORS['foam'], center, glow_size)
    
    def stop(self):
        """Signal the visualization to stop."""
        self._running = False
    
    def run(self):
        """Run the visualization window."""
        pygame.init()
        screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption(self.title)
        clock = pygame.time.Clock()
        
        self._running = True
        while self._running:
            try:
                dt = clock.tick(60) / 1000.0  # Delta time in seconds
                
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self._running = False
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            self._running = False
                        elif event.key == pygame.K_SPACE:
                            # Manual toggle for testing
                            try:
                                if self.speaking_file.exists():
                                    self.speaking_file.unlink()
                                else:
                                    self.speaking_file.touch()
                            except Exception:
                                pass
                
                self.update(dt)
                self.draw(screen)
                pygame.display.flip()
            except Exception as e:
                print(f"Face error: {e}")
                continue
        
        pygame.quit()


def run_face():
    """Entry point for running the face visualization."""
    face = OceanFace()
    face.run()


if __name__ == "__main__":
    run_face()
