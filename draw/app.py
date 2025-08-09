import pygame
import sys
import socket
import json
import threading
import time
import queue
import os
import math
import colorsys

# Initialize Pygame
pygame.init()

# Constants
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 900
GRID_SIZE = 50000
FPS = 30

# Chunk system constants
CHUNK_SIZE = 512  # Size of each chunk (512x512 pixels)
CHUNK_BUFFER = 2  # Load chunks 2 chunks beyond visible area

# Colors
WHITE         = (255, 255, 255)
BLACK         = (0, 0, 0)
GRAY          = (150, 150, 150)
LIGHT_GRAY    = (200, 200, 200)
DARK_GRAY     = (100, 100, 100)
BRIGHT_GRID   = (220, 220, 220)

# Soft colors
SOFT_RED      = (255, 102, 102)
SOFT_GREEN    = (144, 238, 144)
SOFT_BLUE     = (173, 216, 230)
SOFT_YELLOW   = (255, 255, 153)
SOFT_PURPLE   = (216, 191, 216)
SOFT_CYAN     = (180, 255, 255)
SOFT_ORANGE   = (255, 204, 153)

# Pastel & muted tones
PEACH         = (255, 229, 180)
MINT          = (189, 252, 201)
LAVENDER      = (230, 230, 250)
BABY_BLUE     = (137, 207, 240)
BLUSH_PINK    = (255, 192, 203)
CREAM         = (255, 253, 208)
BEIGE         = (245, 245, 220)
SKY_BLUE      = (135, 206, 235)
SAGE_GREEN    = (188, 184, 138)
ROSE          = (255, 102, 204)
MAUVE         = (224, 176, 255)
CORAL         = (255, 160, 122)
SAND          = (237, 201, 175)

# New – darker/earthy/dusky tones
DUSK_BLUE     = (72, 85, 121)
DARK_MAUVE    = (145, 95, 150)
BURNT_ORANGE  = (204, 85, 0)
FOREST_GREEN  = (34, 70, 34)
DEEP_PURPLE   = (75, 0, 130)
SLATE_GRAY    = (112, 128, 144)
CHARCOAL      = (54, 69, 79)
WINE_RED      = (114, 47, 55)
DUSTY_ROSE    = (168, 108, 117)
OLIVE         = (128, 128, 0)
DARK_SAGE     = (107, 124, 89)
MOSS_GREEN    = (119, 136, 96)
STORM_BLUE    = (80, 110, 123)
ASH_BROWN     = (139, 115, 85)
PLUM          = (142, 69, 133)
COCOA         = (120, 90, 70)
INK_BLUE      = (50, 60, 90)
COAL          = (30, 30, 30)
AUBERGINE     = (70, 40, 60)
MUTED_NAVY    = (60, 70, 90)
DARK_BEIGE    = (185, 169, 120)
DEEP_SKY      = (70, 130, 180)
TWILIGHT_PURPLE = (96, 80, 130)
MUTED_CLAY    = (190, 140, 120)


def resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller."""
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, relative_path)


class NetworkClient:
    def __init__(self, host='147.185.221.29', port=9062):
        self.host = host
        self.port = port
        self.socket = None
        self.socket_file = None
        self.connected = False
        self.connection_status = "Disconnected"
        
        # Queue for pixels to send (thread-safe)
        self.pixel_queue = queue.Queue()
        
        # Chunk loading state
        self.requested_chunks = set()  # Track which chunks we've requested
        self.loaded_chunks = set()     # Track which chunks are fully loaded
        self.loading_chunks = set()    # Track chunks currently being loaded
        
        # Keepalive state
        self.last_pong_time = 0.0
        
        self.create_socket()

    def create_socket(self):
        """Create TCP socket"""
        try:
            self.close_socket()
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5.0)
            # Disable Nagle for lower latency updates
            try:
                self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except Exception:
                pass
            print("TCP socket created")
        except Exception as e:
            print(f"Socket creation failed: {e}")

    def close_socket(self):
        try:
            if self.socket_file:
                try:
                    self.socket_file.close()
                except Exception:
                    pass
                self.socket_file = None
            if self.socket:
                try:
                    self.socket.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    self.socket.close()
                except Exception:
                    pass
                self.socket = None
        except Exception:
            pass

    def connect(self):
        """Connect to server"""
        try:
            print(f"Connecting to {self.host}:{self.port}...")
            self.connection_status = "Connecting..."
            self.socket.settimeout(5.0)
            self.socket.connect((self.host, self.port))
            self.socket.settimeout(None)
            self.socket_file = self.socket.makefile('r', encoding='utf-8', newline='\n')

            # Send ping
            ping_msg = {'type': 'ping'}
            self.send_json(ping_msg)

            # Wait for pong
            line = self.socket_file.readline()
            response = json.loads(line) if line else {}
            if response.get('type') == 'pong':
                self.connected = True
                self.connection_status = "Connected"
                self.last_pong_time = time.time()
                print("Connected to server!")
                return True
        except Exception as e:
            print(f"Connection failed: {e}")
            self.connected = False
            self.connection_status = "Connection failed"
            self.create_socket()
        return False

    def send_json(self, obj):
        try:
            if not self.socket:
                return False
            payload = (json.dumps(obj) + "\n").encode('utf-8')
            self.socket.sendall(payload)
            return True
        except Exception as e:
            print(f"send_json failed: {e}")
            self.connected = False
            self.connection_status = "Connection lost"
            self.create_socket()
            return False

    def request_chunk(self, chunk_x, chunk_y):
        """Request a specific chunk from server"""
        if not self.connected:
            return False
        
        chunk_id = (chunk_x, chunk_y)
        if chunk_id in self.requested_chunks or chunk_id in self.loaded_chunks:
            return False
        
        try:
            self.requested_chunks.add(chunk_id)
            self.loading_chunks.add(chunk_id)
            print(f"Requesting chunk ({chunk_x}, {chunk_y})")
            self.send_json({
                'type': 'request_chunk',
                'chunk_x': chunk_x,
                'chunk_y': chunk_y,
                'chunk_size': CHUNK_SIZE
            })
            return True
        except Exception as e:
            print(f"Failed to request chunk: {e}")
            self.requested_chunks.discard(chunk_id)
            self.loading_chunks.discard(chunk_id)
            return False

    def get_required_chunks(self, camera_x, camera_y, zoom, window_width, window_height):
        """Calculate which chunks are needed for the current viewport"""
        # Calculate visible area with buffer
        half_width = (window_width / (2 * zoom)) + (CHUNK_BUFFER * CHUNK_SIZE)
        half_height = (window_height / (2 * zoom)) + (CHUNK_BUFFER * CHUNK_SIZE)
        
        min_x = max(0, int((camera_x - half_width) // CHUNK_SIZE))
        max_x = min(GRID_SIZE // CHUNK_SIZE, int((camera_x + half_width) // CHUNK_SIZE) + 1)
        min_y = max(0, int((camera_y - half_height) // CHUNK_SIZE))
        max_y = min(GRID_SIZE // CHUNK_SIZE, int((camera_y + half_height) // CHUNK_SIZE) + 1)
        
        required_chunks = set()
        for chunk_x in range(min_x, max_x):
            for chunk_y in range(min_y, max_y):
                required_chunks.add((chunk_x, chunk_y))
        
        return required_chunks

    def update_chunk_loading(self, camera_x, camera_y, zoom, window_width, window_height):
        """Update which chunks should be loaded based on viewport"""
        if not self.connected:
            return
            
        required_chunks = self.get_required_chunks(camera_x, camera_y, zoom, window_width, window_height)
        
        # Request new chunks that are needed
        for chunk_id in required_chunks:
            if chunk_id not in self.requested_chunks and chunk_id not in self.loaded_chunks:
                chunk_x, chunk_y = chunk_id
                self.request_chunk(chunk_x, chunk_y)

    def add_pixel(self, x, y, color):
        """Add pixel to send queue"""
        try:
            self.pixel_queue.put({'x': x, 'y': y, 'color': color}, block=False)
        except queue.Full:
            print("Pixel queue full!")

    def send_pixels_worker(self):
        """Worker thread to send pixels every 150ms"""
        while True:
            try:
                if not self.connected:
                    time.sleep(0.1)
                    continue
                # Collect batch
                pixels_to_send = []
                try:
                    while True:
                        pixel = self.pixel_queue.get(block=False)
                        pixels_to_send.append(pixel)
                        if len(pixels_to_send) >= 1000:
                            break
                except queue.Empty:
                    pass

                if pixels_to_send:
                    self.send_json({'type': 'pixel_batch', 'pixels': pixels_to_send})
                time.sleep(0.15)
            except Exception as e:
                print(f"Send worker error: {e}")
                time.sleep(0.5)

    def network_listener(self, canvas):
        """Listen for network messages"""
        print("Network listener started")
        buffer_file = None
        while True:
            try:
                if not self.connected or not self.socket_file:
                    time.sleep(0.1)
                    continue
                if buffer_file is None:
                    buffer_file = self.socket_file

                line = buffer_file.readline()
                if not line:
                    # Server closed
                    raise ConnectionError("server closed")
                message = json.loads(line)
                msg_type = message.get('type')

                if msg_type == 'pong':
                    self.last_pong_time = time.time()
                    self.connection_status = "Connected"
                elif msg_type == 'chunk_data':
                    # Handle chunk data response
                    chunk_x = message.get('chunk_x', 0)
                    chunk_y = message.get('chunk_y', 0)
                    pixels = message.get('pixels', [])
                    chunk_id = (chunk_x, chunk_y)
                    
                    print(f"Received chunk ({chunk_x}, {chunk_y}) with {len(pixels)} pixels")
                    
                    # Add pixels to canvas
                    for pixel in pixels:
                        x = pixel.get('x')
                        y = pixel.get('y')
                        color = pixel.get('color')
                        if x is not None and y is not None and color is not None:
                            canvas.grid[(x, y)] = tuple(color)
                    
                    # Mark chunk as loaded
                    self.loading_chunks.discard(chunk_id)
                    self.loaded_chunks.add(chunk_id)
                    
                elif msg_type == 'canvas_chunk':
                    # Handle old-style canvas chunk for backwards compatibility
                    pixels = message.get('pixels', [])
                    chunk_id = message.get('chunk_id', 0)
                    total_chunks = message.get('total_chunks', 1)
                    print(f"Receiving canvas chunk {chunk_id + 1}/{total_chunks} ({len(pixels)} pixels)")
                    for pixel in pixels:
                        x = pixel.get('x')
                        y = pixel.get('y')
                        color = pixel.get('color')
                        if x is not None and y is not None and color is not None:
                            canvas.grid[(x, y)] = tuple(color)
                elif msg_type == 'canvas_complete':
                    total_pixels = message.get('total_pixels', 0)
                    print(f"Canvas loaded! Total pixels: {total_pixels}")
                elif msg_type == 'pixel_update':
                    pixels = message.get('pixels', [])
                    for pixel in pixels:
                        x = pixel.get('x')
                        y = pixel.get('y')
                        color = pixel.get('color')
                        if x is not None and y is not None:
                            if color is None:
                                if (x, y) in canvas.grid:
                                    del canvas.grid[(x, y)]
                            else:
                                canvas.grid[(x, y)] = tuple(color)
            except Exception as e:
                print(f"Network listener error: {e}")
                self.connected = False
                self.connection_status = "Network error"
                self.create_socket()
                time.sleep(0.5)

    def heartbeat_worker(self):
        """Send periodic pings to keep the connection alive"""
        while True:
            try:
                if self.connected:
                    self.send_json({'type': 'ping'})
                time.sleep(10)
            except Exception as e:
                time.sleep(1)

    def start_threads(self, canvas):
        """Start network threads"""
        def connection_worker():
            retry_delay = 1.0
            while True:
                # Keepalive timeout detection (30s without pong)
                if self.connected and self.last_pong_time:
                    if time.time() - self.last_pong_time > 30:
                        print("Keepalive timeout; reconnecting...")
                        self.connected = False
                        self.connection_status = "Keepalive timeout"
                        self.create_socket()
                        # Reset chunk state on reconnect
                        self.requested_chunks.clear()
                        self.loaded_chunks.clear()
                        self.loading_chunks.clear()

                if not self.connected and self.socket:
                    if self.connect():
                        retry_delay = 1.0
                    else:
                        time.sleep(retry_delay)
                        retry_delay = min(10.0, retry_delay * 1.5)
                time.sleep(1.0)

        threading.Thread(target=connection_worker, daemon=True).start()
        threading.Thread(target=self.send_pixels_worker, daemon=True).start()
        threading.Thread(target=self.network_listener, args=(canvas,), daemon=True).start()
        threading.Thread(target=self.heartbeat_worker, daemon=True).start()


class PixelCanvas:
    def __init__(self):
        # Pygame setup
        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        # Set window icon
        try:
            icon_surface = pygame.image.load(resource_path('uicon.ico'))
            pygame.display.set_icon(icon_surface)
        except Exception as e:
            print(f"Failed to load window icon: {e}")
        pygame.display.set_caption("1010draw")
        self.clock = pygame.time.Clock()

        # Canvas data - stores all pixels {(x, y): (r, g, b)}
        self.grid = {}

        # Network client
        self.network = NetworkClient()
        self.network.start_threads(self)

        # Camera and view
        self.camera_x = GRID_SIZE // 2
        self.camera_y = GRID_SIZE // 2
        self.zoom = 8.0
        self.min_zoom = 0.01
        self.max_zoom = 50.0

        # Track camera movement for chunk loading
        self.last_camera_x = self.camera_x
        self.last_camera_y = self.camera_y
        self.last_zoom = self.zoom
        self.chunk_update_timer = 0

        # Input tracking
        self.middle_mouse_pressed = False
        self.right_mouse_pressed = False
        self.dragging_wheel = False
        self.dragging_value = False
        self.last_mouse_pos = (0, 0)
        self.space_pressed = False

        # Color picker (HSV)
        self.hue = 0.0
        self.saturation = 1.0
        self.value = 1.0
        self.color_picker_radius = 100
        self.color_picker_center = (WINDOW_WIDTH - 160, 160)
        self.value_slider_rect = pygame.Rect(WINDOW_WIDTH - 35, 60, 20, 200)
        self.picker_surface = self.generate_color_wheel_surface(self.color_picker_radius * 2 + 1)
        self.current_color = self.hsv_to_rgb255(self.hue, self.saturation, self.value)

        # UI fonts
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 18)

        print("Pixel Canvas initialized")

    def hsv_to_rgb255(self, h: float, s: float, v: float):
        r, g, b = colorsys.hsv_to_rgb(max(0.0, min(1.0, h)),
                                      max(0.0, min(1.0, s)),
                                      max(0.0, min(1.0, v)))
        return (int(r * 255), int(g * 255), int(b * 255))

    def generate_color_wheel_surface(self, diameter: int) -> pygame.Surface:
        surf = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
        radius = diameter // 2
        for y in range(diameter):
            for x in range(diameter):
                dx = x - radius
                dy = y - radius
                dist = math.hypot(dx, dy)
                if dist <= radius:
                    h = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
                    h /= 360.0
                    s = min(1.0, dist / radius)
                    color = self.hsv_to_rgb255(h, s, 1.0)
                    surf.set_at((x, y), color + (255,))
                else:
                    surf.set_at((x, y), (0, 0, 0, 0))
        return surf

    def update_color_from_wheel(self, mouse_pos):
        cx, cy = self.color_picker_center
        mx, my = mouse_pos
        dx = mx - cx
        dy = my - cy
        dist = math.hypot(dx, dy)
        if dist <= self.color_picker_radius:
            h = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
            self.hue = h / 360.0
            self.saturation = min(1.0, dist / self.color_picker_radius)
            self.current_color = self.hsv_to_rgb255(self.hue, self.saturation, self.value)

    def update_value_from_slider(self, mouse_pos):
        x, y = mouse_pos
        if self.value_slider_rect.collidepoint(x, y):
            # y within slider: top = 60, height = 200 (by rect)
            rel = (y - self.value_slider_rect.top) / max(1, self.value_slider_rect.height)
            rel = max(0.0, min(1.0, rel))
            # top is value 1.0, bottom is 0.0
            self.value = 1.0 - rel
            self.current_color = self.hsv_to_rgb255(self.hue, self.saturation, self.value)

    def update_chunk_loading(self):
        """Update chunk loading based on camera position"""
        # Only update chunks periodically or when camera moves significantly
        current_time = time.time()
        camera_moved = (abs(self.camera_x - self.last_camera_x) > CHUNK_SIZE // 4 or
                       abs(self.camera_y - self.last_camera_y) > CHUNK_SIZE // 4 or
                       abs(self.zoom - self.last_zoom) > self.zoom * 0.1)
        
        if camera_moved or current_time - self.chunk_update_timer > 1.0:
            self.network.update_chunk_loading(
                self.camera_x, self.camera_y, self.zoom, 
                WINDOW_WIDTH, WINDOW_HEIGHT
            )
            self.last_camera_x = self.camera_x
            self.last_camera_y = self.camera_y
            self.last_zoom = self.zoom
            self.chunk_update_timer = current_time

    def screen_to_grid(self, screen_x, screen_y):
        """Convert screen coordinates to grid coordinates"""
        world_x = (screen_x - WINDOW_WIDTH // 2) / self.zoom + self.camera_x
        world_y = (screen_y - WINDOW_HEIGHT // 2) / self.zoom + self.camera_y
        return int(world_x), int(world_y)

    def grid_to_screen(self, grid_x, grid_y):
        """Convert grid coordinates to screen coordinates"""
        world_x = grid_x - self.camera_x
        world_y = grid_y - self.camera_y
        return world_x * self.zoom + WINDOW_WIDTH // 2, world_y * self.zoom + WINDOW_HEIGHT // 2

    def draw_pixel(self, grid_x, grid_y):
        """Draw or erase pixel at grid position"""
        if self.zoom < 4.64:
            return  # Don't draw if zoomed out too far
        if 0 <= grid_x < GRID_SIZE and 0 <= grid_y < GRID_SIZE:
            if self.current_color == WHITE:
                if (grid_x, grid_y) in self.grid:
                    del self.grid[(grid_x, grid_y)]
                self.network.add_pixel(grid_x, grid_y, None)
            else:
                self.grid[(grid_x, grid_y)] = self.current_color
                self.network.add_pixel(grid_x, grid_y, list(self.current_color))

    def erase_pixel(self, grid_x, grid_y):
        """Erase pixel regardless of current color"""
        if self.zoom < 4.64:
            return  # Don't erase if zoomed out too far
        if 0 <= grid_x < GRID_SIZE and 0 <= grid_y < GRID_SIZE:
            if (grid_x, grid_y) in self.grid:
                del self.grid[(grid_x, grid_y)]
            self.network.add_pixel(grid_x, grid_y, None)

    def draw_canvas_background(self):
        """Draw white canvas background"""
        left_screen, top_screen = self.grid_to_screen(0, 0)
        right_screen, bottom_screen = self.grid_to_screen(GRID_SIZE, GRID_SIZE)

        canvas_rect = pygame.Rect(
            max(0, min(WINDOW_WIDTH, left_screen)),
            max(0, min(WINDOW_HEIGHT, top_screen)),
            max(0, min(WINDOW_WIDTH - left_screen, right_screen - left_screen)),
            max(0, min(WINDOW_HEIGHT - top_screen, bottom_screen - top_screen))
        )

        if canvas_rect.width > 0 and canvas_rect.height > 0:
            pygame.draw.rect(self.screen, WHITE, canvas_rect)

    def draw_grid_lines(self):
        """Draw grid lines when zoomed in"""
        if self.zoom < 2:
            return

        left_grid = max(0, int(self.camera_x - WINDOW_WIDTH // (2 * self.zoom) - 1))
        right_grid = min(GRID_SIZE, int(self.camera_x + WINDOW_WIDTH // (2 * self.zoom) + 1))
        top_grid = max(0, int(self.camera_y - WINDOW_HEIGHT // (2 * self.zoom) - 1))
        bottom_grid = min(GRID_SIZE, int(self.camera_y + WINDOW_HEIGHT // (2 * self.zoom) + 1))

        # Vertical lines
        for x in range(left_grid, right_grid + 1):
            screen_x, _ = self.grid_to_screen(x, 0)
            if 0 <= screen_x <= WINDOW_WIDTH:
                pygame.draw.line(self.screen, BRIGHT_GRID, (screen_x, 0), (screen_x, WINDOW_HEIGHT), 1)

        # Horizontal lines
        for y in range(top_grid, bottom_grid + 1):
            _, screen_y = self.grid_to_screen(0, y)
            if 0 <= screen_y <= WINDOW_HEIGHT:
                pygame.draw.line(self.screen, BRIGHT_GRID, (0, screen_y), (WINDOW_WIDTH, screen_y), 1)

    def draw_pixels(self):
        """Draw all visible pixels"""
        left_grid = int(self.camera_x - WINDOW_WIDTH // (2 * self.zoom) - 1)
        right_grid = int(self.camera_x + WINDOW_WIDTH // (2 * self.zoom) + 1)
        top_grid = int(self.camera_y - WINDOW_HEIGHT // (2 * self.zoom) - 1)
        bottom_grid = int(self.camera_y + WINDOW_HEIGHT // (2 * self.zoom) + 1)

        pixel_size = max(1, int(self.zoom))

        for (grid_x, grid_y), color in list(self.grid.items()):
            if left_grid <= grid_x <= right_grid and top_grid <= grid_y <= bottom_grid:
                screen_x, screen_y = self.grid_to_screen(grid_x, grid_y)
                if pixel_size == 1:
                    if 0 <= screen_x < WINDOW_WIDTH and 0 <= screen_y < WINDOW_HEIGHT:
                        self.screen.set_at((int(screen_x), int(screen_y)), color)
                else:
                    rect = pygame.Rect(screen_x, screen_y, pixel_size, pixel_size)
                    pygame.draw.rect(self.screen, color, rect)

    def draw_ui(self):
        """Draw user interface"""
        # Hovered grid position under mouse
        mouse_x, mouse_y = pygame.mouse.get_pos()
        hover_x, hover_y = self.screen_to_grid(mouse_x, mouse_y)

        info_texts = [
            f"Zoom: {self.zoom:.2f}x",
            f"Position: ({int(hover_x)}, {int(hover_y)})",
            f"Pixels loaded: {len(self.grid)}",
            f"Chunks loaded: {len(self.network.loaded_chunks)}",
            f"Chunks loading: {len(self.network.loading_chunks)}",
            f"Color: {self.current_color[0]},{self.current_color[1]},{self.current_color[2]}",
            "Controls:",
            "• Mouse wheel: Zoom",
            "• Middle mouse: Pan",
            "• Left click: Draw",
            "• Right click: Erase",
            "• Shift + Left click: Eyedropper",
            "• Space + mouse: Paint",
            "• Arrow keys: Move camera"
        ]

        y_pos = 50
        for text in info_texts:
            color = WHITE if text.startswith(('•', 'Controls:')) else SOFT_YELLOW
            self.draw_text_with_shadow(text, 10, y_pos, color)
            y_pos += 22

        # Show warning if zoom is too low for drawing
        if self.zoom < 4.64:
            warning_text = "Zoom in to draw (min 4.64x)"
            warning_surface = self.font.render(warning_text, True, SOFT_RED)
            self.screen.blit(warning_surface, (10, y_pos))

        # Color picker UI (wheel)
        wheel_diam = self.color_picker_radius * 2 + 1
        wheel_topleft = (self.color_picker_center[0] - self.color_picker_radius,
                         self.color_picker_center[1] - self.color_picker_radius)
        self.screen.blit(self.picker_surface, wheel_topleft)
        # Wheel marker
        angle = self.hue * 2 * math.pi
        r = self.saturation * self.color_picker_radius
        marker_x = int(self.color_picker_center[0] + math.cos(angle) * r)
        marker_y = int(self.color_picker_center[1] + math.sin(angle) * r)
        pygame.draw.circle(self.screen, BLACK, (marker_x, marker_y), 5, 2)

        # Value slider gradient (top=1.0 -> bottom=0.0)
        for i in range(self.value_slider_rect.height):
            v = 1.0 - (i / max(1, self.value_slider_rect.height - 1))
            col = self.hsv_to_rgb255(self.hue, self.saturation, v)
            pygame.draw.line(self.screen, col,
                             (self.value_slider_rect.left, self.value_slider_rect.top + i),
                             (self.value_slider_rect.right, self.value_slider_rect.top + i))
        # Slider border and handle
        pygame.draw.rect(self.screen, BLACK, self.value_slider_rect, 2)
        handle_y = int(self.value_slider_rect.top + (1.0 - self.value) * self.value_slider_rect.height)
        pygame.draw.rect(self.screen, WHITE, (self.value_slider_rect.left - 2, handle_y - 2,
                                              self.value_slider_rect.width + 4, 4))

        # Current color swatch
        swatch_rect = pygame.Rect(self.value_slider_rect.left - 10, self.value_slider_rect.bottom + 10, 40, 20)
        pygame.draw.rect(self.screen, self.current_color, swatch_rect)
        pygame.draw.rect(self.screen, BLACK, swatch_rect, 2)

        # Network status
        if len(self.network.loading_chunks) > 0:
            status_text = f"Loading chunks... ({len(self.network.loading_chunks)} pending)"
            status_color = SOFT_YELLOW
        elif self.network.connected:
            status_text = f"Connected • {self.network.pixel_queue.qsize()} pending • {len(self.network.loaded_chunks)} chunks"
            status_color = SOFT_GREEN
        else:
            status_text = self.network.connection_status
            status_color = SOFT_RED

        status_surface = self.small_font.render(status_text, True, status_color)
        self.screen.blit(status_surface, (10, WINDOW_HEIGHT - 25))

    def draw_text_with_shadow(self, text, x, y, color, shadow_color=BLACK):
        """Draw text with shadow"""
        shadow = self.font.render(text, True, shadow_color)
        self.screen.blit(shadow, (x + 2, y + 2))
        main_text = self.font.render(text, True, color)
        self.screen.blit(main_text, (x, y))

    def handle_events(self):
        """Handle all pygame events"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            elif event.type == pygame.KEYDOWN:
                move_speed = 10 / self.zoom
                if event.key == pygame.K_LEFT:
                    self.camera_x -= move_speed
                elif event.key == pygame.K_RIGHT:
                    self.camera_x += move_speed
                elif event.key == pygame.K_UP:
                    self.camera_y -= move_speed
                elif event.key == pygame.K_DOWN:
                    self.camera_y += move_speed
                elif event.key == pygame.K_SPACE:
                    self.space_pressed = True

            elif event.type == pygame.KEYUP:
                if event.key == pygame.K_SPACE:
                    self.space_pressed = False

            elif event.type == pygame.MOUSEBUTTONDOWN:
                mods = pygame.key.get_mods()
                if event.button == 1:
                    # Shift + left click: eyedropper (do not draw)
                    if mods & pygame.KMOD_SHIFT:
                        grid_x, grid_y = self.screen_to_grid(*event.pos)
                        picked = self.grid.get((grid_x, grid_y), WHITE)
                        self.current_color = picked
                        # Update HSV to match picked color for the UI
                        r, g, b = picked
                        hr, hg, hb = r / 255.0, g / 255.0, b / 255.0
                        h, s, v = colorsys.rgb_to_hsv(hr, hg, hb)
                        self.hue, self.saturation, self.value = h, s, v
                        continue
                    # Color wheel / slider interaction
                    cx, cy = self.color_picker_center
                    dx = event.pos[0] - cx
                    dy = event.pos[1] - cy
                    if math.hypot(dx, dy) <= self.color_picker_radius:
                        self.dragging_wheel = True
                        self.update_color_from_wheel(event.pos)
                        continue
                    if self.value_slider_rect.collidepoint(event.pos):
                        self.dragging_value = True
                        self.update_value_from_slider(event.pos)
                        continue
                    # Draw pixel on canvas
                    grid_x, grid_y = self.screen_to_grid(*event.pos)
                    self.draw_pixel(grid_x, grid_y)
                elif event.button == 2:
                    self.middle_mouse_pressed = True
                    self.last_mouse_pos = event.pos
                elif event.button == 3:
                    self.right_mouse_pressed = True
                    grid_x, grid_y = self.screen_to_grid(*event.pos)
                    self.erase_pixel(grid_x, grid_y)

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 2:
                    self.middle_mouse_pressed = False
                elif event.button == 3:
                    self.right_mouse_pressed = False
                elif event.button == 1:
                    self.dragging_wheel = False
                    self.dragging_value = False

            elif event.type == pygame.MOUSEMOTION:
                if self.middle_mouse_pressed:
                    dx = event.pos[0] - self.last_mouse_pos[0]
                    dy = event.pos[1] - self.last_mouse_pos[1]
                    self.camera_x -= dx / self.zoom
                    self.camera_y -= dy / self.zoom
                    self.last_mouse_pos = event.pos
                elif self.dragging_wheel:
                    self.update_color_from_wheel(event.pos)
                elif self.dragging_value:
                    self.update_value_from_slider(event.pos)
                elif self.right_mouse_pressed:
                    grid_x, grid_y = self.screen_to_grid(*event.pos)
                    self.erase_pixel(grid_x, grid_y)
                elif self.space_pressed and not (pygame.key.get_mods() & pygame.KMOD_SHIFT):
                    grid_x, grid_y = self.screen_to_grid(*event.pos)
                    self.draw_pixel(grid_x, grid_y)

            elif event.type == pygame.MOUSEWHEEL:
                mouse_x, mouse_y = pygame.mouse.get_pos()
                world_x_before = (mouse_x - WINDOW_WIDTH // 2) / self.zoom + self.camera_x
                world_y_before = (mouse_y - WINDOW_HEIGHT // 2) / self.zoom + self.camera_y
                zoom_factor = 1.2 if event.y > 0 else 1 / 1.2
                self.zoom = max(self.min_zoom, min(self.max_zoom, self.zoom * zoom_factor))
                world_x_after = (mouse_x - WINDOW_WIDTH // 2) / self.zoom + self.camera_x
                world_y_after = (mouse_y - WINDOW_HEIGHT // 2) / self.zoom + self.camera_y
                self.camera_x += world_x_before - world_x_after
                self.camera_y += world_y_before - world_y_after

        self.camera_x = max(0, min(GRID_SIZE, self.camera_x))
        self.camera_y = max(0, min(GRID_SIZE, self.camera_y))
        return True

    def run(self):
        """Main game loop"""
        print("Starting pixel canvas application")
        running = True
        while running:
            running = self.handle_events()
            
            # Update chunk loading based on camera position
            self.update_chunk_loading()
            
            self.screen.fill(LIGHT_GRAY)
            self.draw_canvas_background()
            self.draw_grid_lines()
            self.draw_pixels()
            self.draw_ui()
            pygame.display.flip()
            self.clock.tick(FPS)

        print("Shutting down...")
        if self.network.socket:
            self.network.close_socket()
        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    app = PixelCanvas()
    app.run()