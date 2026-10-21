"""Versioned native-diagram template. No generated/raster illustrations."""
from __future__ import annotations

import math

from production.animation_plan import orbit_state

BACKGROUND = "#0B1526"
WHITE = "#F2F4F7"
CYAN = "#60DEEC"
ORANGE = "#FFB76B"


def shape(name, geometry, x, y, w, h, fill, *, stroke="none", rotation=0, text="", size=26):
    return {"name": name, "geometry": geometry, "position": {
        "left": round(x, 4), "top": round(y, 4), "width": w, "height": h, "rotation": rotation},
        "fill": fill, "line": {"fill": stroke, "width": 2 if stroke != "none" else 0},
        "text": text, "font_size": size}


def text(name, value, x, y, width, height, size=26, color=WHITE):
    item = shape(name, "textbox", x, y, width, height, "none", text=value, size=size)
    item["color"] = color
    return item


def diagram_state(component, progress, prefix=""):
    state = orbit_state(component, progress)
    x, y = state["moon"]
    result = [shape(prefix + "moon", "ellipse", x-14, y-14, 28, 28, WHITE)]
    for role, length, color in [("velocity", 90, CYAN), ("gravity", 95, ORANGE)]:
        dx, dy = state[role]
        # Arrow begins just beyond the moon edge and rotates about its centre.
        mx, my = x + dx * (length/2 + 19), y + dy * (length/2 + 19)
        result.append(shape(prefix + role, "rightArrow", mx-length/2, my-7, length, 14, color,
                            rotation=math.degrees(math.atan2(dy, dx)) % 360))
    return result


def build_scene(page: dict, fps: int = 30) -> dict:
    actions = {a["op"]: a for a in page["actions"]}
    duration = page["duration_frames"]
    objects = [
        text("title", page["title"], 70, 48, 1130, 68, 42),
        text("question", "月球为什么绕着地球运动", 72, 172, 525, 60, 30),
        text("velocity_label", "速度沿轨道切线方向", 72, 286, 475, 60, 28, CYAN),
        text("gravity_label", "引力持续指向地球", 72, 372, 475, 60, 28, ORANGE),
        text("conclusion", "引力改变运动方向，形成轨道", 72, 512, 1120, 65, 30),
        text("disclosure", "简化圆轨道模型，非比例示意", 72, 620, 900, 40, 23, "#B4BFCE"),
        shape("orbit", "ellipse", 715, 200, 300, 300, "none", stroke="#52647C"),
        shape("earth", "ellipse", 830, 315, 70, 70, "#568ECA"),
        text("earth_label", "地球", 820, 403, 95, 45, 24),
    ]
    visibility = {o["name"]: [[0, duration]] for o in objects}
    for name, op in [("velocity_label", "reveal_velocity"), ("gravity_label", "reveal_gravity"),
                     ("conclusion", "conclude")]:
        visibility[name] = [[actions[op]["start_frame"], duration]]
    start, end = actions["orbit"]["start_frame"], actions["orbit"]["end_frame"]
    for item in diagram_state(page['component'], 0, 'initial_'):
        role = item['name'].split('_', 1)[1]
        objects.append(item)
        visible_from = 0 if role == 'moon' else actions[f'reveal_{role}']['start_frame']
        visibility[item['name']] = [[visible_from, start]]
    # Rigid rotation around a transparent, symmetric bounding box preserves
    # radial gravity and tangential velocity continuously using native Spin.
    rig = [shape('rig_bounds', 'rect', 605, 90, 520, 520, 'none'),
           *diagram_state(page['component'], 0, 'rig_')]
    objects.extend(rig)
    visibility['orbit_rig'] = [[start, duration]]
    return {"background": BACKGROUND, "objects": objects, "visibility": visibility,
            "component": page['component'],
            "groups": [{'name': 'orbit_rig', 'members': [x['name'] for x in rig]}],
            "rotations": [{'target': 'orbit_rig', 'start_frame': start, 'end_frame': end,
                           'degrees': page['component']['sweep_deg']}],
            "duration_frames": duration, "fps": fps,
            "preview_frames": sorted({0, actions['reveal_gravity']['start_frame']+1,
                                      (start+end)//2, actions['conclude']['start_frame']+1})}


def visible_objects(scene: dict, frame: int) -> list[dict]:
    result = [obj for obj in scene['objects'] if any(a <= frame < b for a,b in scene['visibility'].get(obj['name'], []))]
    rotation = scene['rotations'][0]
    if frame >= rotation['start_frame']:
        progress = min(1, (frame-rotation['start_frame'])/(rotation['end_frame']-rotation['start_frame']))
        result.extend(diagram_state(scene['component'], progress, 'rig_'))
    return result
