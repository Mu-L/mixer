# GPLv3 License
#
# Copyright (C) 2020 Ubisoft
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
Proxy for Armature datablock

See synchronization.md
"""
from __future__ import annotations

import logging
from typing import Optional, Union, TYPE_CHECKING

import bpy
import bpy.types as T  # noqa

from mixer.blender_data.datablock_proxy import DatablockProxy
from mixer.blender_data.json_codec import serialize
from mixer.blender_data.attributes import write_attribute

if TYPE_CHECKING:
    from mixer.blender_data.bpy_data_proxy import Context, Delta
    from mixer.blender_data.proxy import Proxy
    from mixer.blender_data.struct_proxy import StructProxy


DEBUG = True

logger = logging.getLogger(__name__)


def override_context():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                override = bpy.context.copy()
                override["window"] = window
                override["screen"] = window.screen
                override["area"] = window.screen.areas[0]
                return override
    return None


@serialize
class ArmatureProxy(DatablockProxy):
    """
    Proxy for an Armature datablock. This specialization is required to switch between current mode and edit mode
    in order to read/write edit_bones.
    """

    _edit_bones_map = {}

    def find_armature_parent_object(self, datablock: T.Armature) -> T.Object:
        for obj in bpy.data.objects:
            if obj.data == datablock:
                return obj

    def _save(self, datablock: T.Armature, context: Context) -> T.Armature:
        datablock = self._pre_save(datablock, context)
        if datablock is None:
            logger.warning(f"DatablockProxy.update_standalone_datablock() {self} pre_save returns None")
            return None, None

        with context.visit_state.enter_datablock(self, datablock):
            for k, v in self._data.items():
                if k != "edit_bones":
                    write_attribute(datablock, k, v, context)
                else:
                    ArmatureProxy._edit_bones_map[datablock.mixer_uuid] = v

        self._custom_properties.save(datablock)
        return datablock

    def load(self, datablock: T.Armature, context: Context) -> ArmatureProxy:
        obj = self.find_armature_parent_object(datablock)
        if not obj:
            return self
        ctx = override_context()
        ctx["active_object"] = obj
        previous_mode = ctx["mode"]
        # TODO logger les retours
        bpy.ops.object.mode_set(ctx, mode="EDIT")
        super().load(datablock, context)
        bpy.ops.object.mode_set(ctx, mode=previous_mode)
        return self

    def _diff(self, armature: T.Armature, key: str, prop: T.Property, context: Context, diff: Proxy) -> Optional[Delta]:

        # switch to edit mode
        prev_active = bpy.context.view_layer.objects.active
        prev_active_mode = prev_active.mode

        obj = self.find_armature_parent_object(armature)
        bpy.context.view_layer.objects.active = obj
        prev_obj_mode = obj.mode
        bpy.ops.object.mode_set(mode="EDIT")

        res = super()._diff(armature, key, prop, context, diff)

        # switch back to previous mode
        bpy.ops.object.mode_set(mode=prev_obj_mode)
        bpy.context.view_layer.objects.active = prev_active
        bpy.ops.object.mode_set(mode=prev_active_mode)

        return res

    def apply(
        self,
        attribute: T.Armature,
        parent: T.BlendDataObjects,
        key: Union[int, str],
        delta: Delta,
        context: Context,
        to_blender: bool = True,
    ) -> StructProxy:
        """
        Apply delta to this proxy and optionally to the Blender attribute its manages.

        Args:
            attribute: the Object datablock to update
            parent: the attribute that contains attribute (e.g. a bpy.data.objects)
            key: the key that identifies attribute in parent.
            delta: the delta to apply
            context: proxy and visit state
            to_blender: update the managed Blender attribute in addition to this Proxy
        """
        assert isinstance(key, str)

        # change mode is needed even for proxy only update to have access to edit_bones
        prev_active = bpy.context.view_layer.objects.active
        prev_active_mode = prev_active.mode

        obj = self.find_armature_parent_object(attribute)
        bpy.context.view_layer.objects.active = obj
        prev_obj_mode = obj.mode
        bpy.ops.object.mode_set(mode="EDIT")

        updated_proxy = super().apply(attribute, parent, key, delta, context, to_blender)

        # switch back to previous mode
        bpy.ops.object.mode_set(mode=prev_obj_mode)
        bpy.context.view_layer.objects.active = prev_active
        bpy.ops.object.mode_set(mode=prev_active_mode)

        return updated_proxy

    @staticmethod
    def apply_edit_bones(obj: T.Object, context: Context):
        if not isinstance(obj.data, T.Armature):
            return
        edit_bones = ArmatureProxy._edit_bones_map.get(obj.data.mixer_uuid)
        if edit_bones is None:
            logger.error("No edit bones found")
            return

        if len(edit_bones) == 0:
            return

        # hack: resolve collection -> object link
        context.proxy_state.unresolved_refs.resolve(obj.mixer_uuid, obj)

        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")

        try:
            write_attribute(obj.data, "edit_bones", edit_bones, context)
        except Exception:
            pass
        del ArmatureProxy._edit_bones_map[obj.data.mixer_uuid]

        bpy.ops.object.mode_set(mode="OBJECT")
