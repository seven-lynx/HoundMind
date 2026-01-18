"""
A* path planning for grid/graph maps (for Pi4).
"""
import heapq

def astar(grid, start, goal, passable=lambda v: v == 0):
    """
    grid: 2D list/array, 0=free, 1=obstacle
    start, goal: (x, y) tuples
    passable: function to check if a cell is traversable
    Returns: list of (x, y) from start to goal, or [] if no path
    """
    w, h = len(grid[0]), len(grid)
    open_set = [(0 + abs(goal[0]-start[0]) + abs(goal[1]-start[1]), 0, start, [start])]
    closed = set()
    while open_set:
        est, cost, node, path = heapq.heappop(open_set)
        if node == goal:
            return path
        if node in closed:
            continue
        closed.add(node)
        x, y = node
        for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]:
            nx, ny = x+dx, y+dy
            if 0 <= nx < w and 0 <= ny < h and passable(grid[ny][nx]) and (nx,ny) not in closed:
                heapq.heappush(open_set, (cost+1+abs(goal[0]-nx)+abs(goal[1]-ny), cost+1, (nx,ny), path+[(nx,ny)]))
    return []

def default_path_planning_hook(mapping_state, sample, settings):
    """
    Example hook: plan from current to goal using A* on a grid map.
    mapping_state: dict with 'samples' and (optionally) 'grid_map'
    settings: config dict, may include 'goal' as (x, y)
    Returns: dict with 'path' and 'success'
    """
    grid = mapping_state.get('grid_map')
    start = mapping_state.get('current_cell')
    goal = settings.get('goal')
    if not (grid and start and goal):
        return {'path': [], 'success': False}
    path = astar(grid, start, goal)
    return {'path': path, 'success': bool(path)}
