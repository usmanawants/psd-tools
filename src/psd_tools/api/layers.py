"""
Layer module.
"""

from __future__ import absolute_import, unicode_literals

import logging

from psd_tools.api import deprecated
from psd_tools.api.effects import Effects
from psd_tools.api.mask import Mask
from psd_tools.api.shape import Origination, Stroke, VectorMask
from psd_tools.api.smart_object import SmartObject
from psd_tools.constants import BlendMode, Clipping, Tag, TextType
from psd_tools.psd.layer_and_mask import *
from psd_tools.psd.tagged_blocks import *


logger = logging.getLogger(__name__)


class Layer(object):
    def __init__(self, psd, record, channels, parent):
        self._psd = psd
        self._record = record
        self._channels = channels
        self._parent = parent
        self._clip_layers = []
        self._has_clip_target = True

    @property
    def name(self):
        """
        Layer name. Writable.

        :return: `str`
        """
        return self._record.tagged_blocks.get_data(
            Tag.UNICODE_LAYER_NAME, self._record.name
        )

    @name.setter
    def name(self, value):
        assert len(value) < 256, "Layer name too long (%d) %s" % (len(value), value)
        try:
            value.encode("macroman")
            self._record.name = value
        except UnicodeEncodeError:
            self._record.name = str("?")
        self._record.tagged_blocks.set_data(Tag.UNICODE_LAYER_NAME, value)

    @property
    def kind(self):
        """
        Kind of this layer, such as group, pixel, shape, type, smartobject,
        or psdimage. Class name without `layer` suffix.

        :return: `str`
        """
        return self.__class__.__name__.lower().replace("layer", "")

    @property
    def layer_id(self):
        """
        Layer ID.

        :return: int layer id. if the layer is not assigned an id, -1.
        """
        return self.tagged_blocks.get_data(Tag.LAYER_ID, -1)

    def _invalidate_bbox(self):
        """
        Invalidate this layer's _bbox and any parents recursively to the root.
        """
        current = self
        while current is not None:
            if hasattr(current, "_bbox"):
                delattr(current, "_bbox")
            current = current.parent

    @property
    def visible(self):
        """
        Layer visibility. Doesn't take group visibility in account. Writable.

        :return: `bool`
        """
        return self._record.flags.visible

    @visible.setter
    def visible(self, value):
        self._invalidate_bbox()
        self._record.flags.visible = bool(value)

    def is_visible(self):
        """
        Layer visibility. Takes group visibility in account.

        :return: `bool`
        """
        return self.visible and self.parent.is_visible()

    @property
    def opacity(self):
        """
        Opacity of this layer in [0, 255] range. Writable.

        :return: int
        """
        return self._record.opacity

    @opacity.setter
    def opacity(self, value):
        assert 0 <= value and value <= 255
        self._record.opacity = int(value)

    @property
    def parent(self):
        """Parent of this layer."""
        return self._parent

    def is_group(self):
        """
        Return True if the layer is a group.

        :return: `bool`
        """
        return isinstance(self, GroupMixin)

    @property
    def blend_mode(self):
        """
        Blend mode of this layer. Writable.

        Example::

            from psd_tools.constants import BlendMode
            if layer.blend_mode == BlendMode.NORMAL:
                layer.blend_mode = BlendMode.SCREEN

        :return: :py:class:`~psd_tools.constants.BlendMode`.
        """
        return self._record.blend_mode

    @blend_mode.setter
    def blend_mode(self, value):
        self._record.blend_mode = BlendMode(value)

    @property
    def left(self):
        """
        Left coordinate. Writable.

        :return: int
        """
        return self._record.left

    @left.setter
    def left(self, value):
        self._invalidate_bbox()
        w = self.width
        self._record.left = int(value)
        self._record.right = int(value) + w

    @property
    def top(self):
        """
        Top coordinate. Writable.

        :return: int
        """
        return self._record.top

    @top.setter
    def top(self, value):
        self._invalidate_bbox()
        h = self.height
        self._record.top = int(value)
        self._record.bottom = int(value) + h

    @property
    def right(self):
        """
        Right coordinate.

        :return: int
        """
        return self._record.right

    @property
    def bottom(self):
        """
        Bottom coordinate.

        :return: int
        """
        return self._record.bottom

    @property
    def width(self):
        """
        Width of the layer.

        :return: int
        """
        return self.right - self.left

    @property
    def height(self):
        """
        Height of the layer.

        :return: int
        """
        return self.bottom - self.top

    @property
    def offset(self):
        """
        (left, top) tuple. Writable.

        :return: `tuple`
        """
        return self.left, self.top

    @offset.setter
    def offset(self, value):
        self.left, self.top = tuple(int(x) for x in value)

    @property
    def size(self):
        """
        (width, height) tuple.

        :return: `tuple`
        """
        return self.width, self.height

    @property
    def bbox(self):
        """(left, top, right, bottom) tuple."""
        return self.left, self.top, self.right, self.bottom

    def has_pixels(self):
        """
        Returns True if the layer has associated pixels. When this is True,
        `topil` method returns :py:class:`PIL.Image`.

        :return: `bool`
        """
        return any(
            ci.id >= 0 and cd.data and len(cd.data) > 0
            for ci, cd in zip(self._record.channel_info, self._channels)
        )

    def has_mask(self):
        """
        Returns True if the layer has a mask.

        :return: `bool`
        """
        return self._record.mask_data is not None

    @property
    def mask(self):
        """
        Returns mask associated with this layer.

        :return: :py:class:`~psd_tools.api.mask.Mask` or `None`
        """
        if not hasattr(self, "_mask"):
            self._mask = Mask(self) if self.has_mask() else None
        return self._mask

    def has_vector_mask(self):
        """
        Returns True if the layer has a vector mask.

        :return: `bool`
        """
        return any(
            key in self.tagged_blocks
            for key in (Tag.VECTOR_MASK_SETTING1, Tag.VECTOR_MASK_SETTING2)
        )

    @property
    def vector_mask(self):
        """
        Returns vector mask associated with this layer.

        :return: :py:class:`~psd_tools.api.shape.VectorMask` or `None`
        """
        if not hasattr(self, "_vector_mask"):
            self._vector_mask = None
            blocks = self.tagged_blocks
            for key in (Tag.VECTOR_MASK_SETTING1, Tag.VECTOR_MASK_SETTING2):
                if key in blocks:
                    self._vector_mask = VectorMask(blocks.get_data(key))
                    break
        return self._vector_mask

    def has_origination(self):
        """
        Returns True if the layer has live shape properties.

        :return: `bool`
        """
        if self.origination:
            return True
        return False

    @property
    def origination(self):
        """
        Property for a list of live shapes or a line.

        Some of the vector masks have associated live shape properties, that
        are Photoshop feature to handle primitive shapes such as a rectangle,
        an ellipse, or a line. Vector masks without live shape properties are
        plain path objects.

        See :py:mod:`psd_tools.api.shape`.

        :return: List of :py:class:`~psd_tools.api.shape.Invalidated`,
            :py:class:`~psd_tools.api.shape.Rectangle`,
            :py:class:`~psd_tools.api.shape.RoundedRectangle`,
            :py:class:`~psd_tools.api.shape.Ellipse`, or
            :py:class:`~psd_tools.api.shape.Line`.
        """
        if not hasattr(self, "_origination"):
            data = self.tagged_blocks.get_data(Tag.VECTOR_ORIGINATION_DATA, {})
            self._origination = [
                Origination.create(x)
                for x in data.get(b"keyDescriptorList", [])
                if not data.get(b"keyShapeInvalidated")
            ]
        return self._origination

    def has_stroke(self):
        """Returns True if the shape has a stroke."""
        return Tag.VECTOR_STROKE_DATA in self.tagged_blocks

    @property
    def stroke(self):
        """Property for strokes."""
        if not hasattr(self, "_stroke"):
            self._stroke = None
            stroke = self.tagged_blocks.get_data(Tag.VECTOR_STROKE_DATA)
            if stroke:
                self._stroke = Stroke(stroke)
        return self._stroke

    def topil(self, channel=None, apply_icc=False):
        """
        Get PIL Image of the layer.

        :param channel: Which channel to return; e.g., 0 for 'R' channel in RGB
            image. See :py:class:`~psd_tools.constants.ChannelID`. When `None`,
            the method returns all the channels supported by PIL modes.
        :param apply_icc: Whether to apply ICC profile conversion to sRGB.
        :return: :py:class:`PIL.Image`, or `None` if the layer has no pixels.

        Example::

            from psd_tools.constants import ChannelID

            image = layer.topil()
            red = layer.topil(ChannelID.CHANNEL_0)
            alpha = layer.topil(ChannelID.TRANSPARENCY_MASK)

        .. note:: Not all of the PSD image modes are supported in
            :py:class:`PIL.Image`. For example, 'CMYK' mode cannot include
            alpha channel in PIL. In this case, topil drops alpha channel.
        """
        from .pil_io import convert_layer_to_pil

        return convert_layer_to_pil(self, channel, apply_icc)


    @deprecated
    def compose(self, force=False, bbox=None, layer_filter=None):
        """
        Deprecated, use :py:func:`~psd_tools.api.layers.PixelLayer.composite`.

        Compose layer and masks (mask, vector mask, and clipping layers).

        Note that the resulting image size is not necessarily equal to the
        layer size due to different mask dimensions. The offset of the
        composed image is stored at `.info['offset']` attribute of `PIL.Image`.

        :param bbox: Viewport bounding box specified by (x1, y1, x2, y2) tuple.
        :return: :py:class:`PIL.Image`, or `None` if the layer has no pixel.
        """
        from psd_tools.composer import compose, compose_layer

        if self.bbox == (0, 0, 0, 0):
            return None
        if bbox is None:
            return compose_layer(self, force=force)
        return compose(self, force=force, bbox=bbox, layer_filter=layer_filter)

    def numpy(self, channel=None, real_mask=True):
        """
        Get NumPy array of the layer.

        :param channel: Which channel to return, can be 'color',
            'shape', 'alpha', or 'mask'. Default is 'color+alpha'.
        :return: :py:class:`numpy.ndarray` or None if there is no pixel.
        """
        from .numpy_io import get_array

        return get_array(self, channel, real_mask=real_mask)

    def composite(
        self,
        viewport=None,
        force=False,
        color=1.0,
        alpha=0.0,
        layer_filter=None,
        apply_icc=False,
    ):
        """
        Composite layer and masks (mask, vector mask, and clipping layers).

        :param viewport: Viewport bounding box specified by (x1, y1, x2, y2)
            tuple. Default is the layer's bbox.
        :param force: Boolean flag to force vector drawing.
        :param color: Backdrop color specified by scalar or tuple of scalar.
            The color value should be in [0.0, 1.0]. For example, (1., 0., 0.)
            specifies red in RGB color mode.
        :param alpha: Backdrop alpha in [0.0, 1.0].
        :param layer_filter: Callable that takes a layer as argument and
            returns whether if the layer is composited. Default is
            :py:func:`~psd_tools.api.layers.PixelLayer.is_visible`.
        :return: :py:class:`PIL.Image`.
        """
        from psd_tools.composite import composite_pil

        return composite_pil(
            self, color, alpha, viewport, layer_filter, force, apply_icc=apply_icc
        )

    def has_clip_layers(self):
        """
        Returns True if the layer has associated clipping.

        :return: `bool`
        """
        return len(self.clip_layers) > 0

    @property
    def clip_layers(self):
        """
        Clip layers associated with this layer.

        To compose clipping layers::

            from psd_tools import compose
            clip_mask = compose(layer.clip_layers)

        :return: list of layers
        """
        return self._clip_layers

    @property
    def clipping_layer(self):
        """
        Clipping flag for this layer. Writable.

        :return: `bool`
        """
        return self._record.clipping == Clipping.NON_BASE

    @clipping_layer.setter
    def clipping_layer(self, value):
        self._record.clipping = Clipping.NON_BASE if value else Clipping.Base
        self._psd._compute_clipping_layers()

    def has_effects(self):
        """
        Returns True if the layer has effects.

        :return: `bool`
        """
        has_effect_tag = any(
            tag in self.tagged_blocks
            for tag in (
                Tag.OBJECT_BASED_EFFECTS_LAYER_INFO,
                Tag.OBJECT_BASED_EFFECTS_LAYER_INFO_V0,
                Tag.OBJECT_BASED_EFFECTS_LAYER_INFO_V1,
            )
        )
        if not has_effect_tag:
            return False
        if not self.effects.enabled:
            return False
        for effect in self.effects:
            if effect.enabled:
                return True
        return False

    @property
    def effects(self):
        """
        Layer effects.

        :return: :py:class:`~psd_tools.api.effects.Effects`
        """
        if not hasattr(self, "_effects"):
            self._effects = Effects(self)
        return self._effects

    @property
    def tagged_blocks(self):
        """
        Layer tagged blocks that is a dict-like container of settings.

        See :py:class:`psd_tools.constants.Tag` for available
        keys.

        :return: :py:class:`~psd_tools.psd.tagged_blocks.TaggedBlocks` or
            `None`.

        Example::

            from psd_tools.constants import Tag
            metadata = layer.tagged_blocks.get_data(Tag.METADATA_SETTING)
        """
        return self._record.tagged_blocks

    def __repr__(self):
        has_size = self.width > 0 and self.height > 0
        return "%s(%r%s%s%s%s)" % (
            self.__class__.__name__,
            self.name,
            " size=%dx%d" % (self.width, self.height) if has_size else "",
            " invisible" if not self.visible else "",
            " mask" if self.has_mask() else "",
            " effects" if self.has_effects() else "",
        )


    # Structure operations, supposes unique references to layers, deep copy might be needed in the future
    def delete_layer(self):
        """
        Deletes the layer and all its child layers if the layer is a group
        """

        self.parent._remove(self)

        # Garbage collection ftw
        return self

    def move_to_group(self, group):
        """
        Moves the layer to the given group, updates the tree metadata as needed.
        """

        if group is self:
            return self

        if self._psd is None:
            if group.kind == "psdimage":
                self._psd = group
            else:
                self._psd = group._psd

        if self in self.parent:
            self._parent._remove(self)
        
        group._append(self)
        self._parent = group
        
        return self

    def move_up(self, ranks = 1):
        """
        Moves the layer up a certain number of ranks in the group the layer is in.
        """

        newrank = self._parent.index(self) - ranks

        if newrank < 0:
            newrank = 0
        elif newrank >= len(self.parent):
            newrank = len(self.parent) - 1

        self._parent._remove(self)
        self._parent._insert(newrank, self)

        return self

    def move_down(self, ranks = 1):
        """
        Moves the layer down a certain number of ranks in the group the layer is in.
        """

        newrank = self._parent.index(self) + ranks

        if newrank < 0:
            newrank = 0
        elif newrank >= len(self.parent):
            newrank = len(self.parent) - 1

        self._parent._remove(self)
        self._parent._insert(newrank, self)

        return self

class GroupMixin(object):
    @property
    def left(self):
        return self.bbox[0]

    @property
    def top(self):
        return self.bbox[1]

    @property
    def right(self):
        return self.bbox[2]

    @property
    def bottom(self):
        return self.bbox[3]

    @property
    def bbox(self):
        """(left, top, right, bottom) tuple."""
        if not hasattr(self, "_bbox"):
            self._bbox = Group.extract_bbox(self)
        return self._bbox

    def add_layer(self, layer):
        """
        Add a layer to the end (top) of the group

        :param layer: The layer to add
        """

        if layer is self:
            return layer

        if layer._psd is None:
            if self.kind == "psdimage":
                layer._psd = self
            else:
                layer._psd = self._psd

        layer._parent = self
        self._layers.append(layer)
        
        return layer

    def __len__(self):
        return self._layers.__len__()

    def __iter__(self):
        return self._layers.__iter__()

    def __getitem__(self, key):
        return self._layers.__getitem__(key)

    def __setitem__(self, key, value):
        return self._layers.__setitem__(key, value)

    def __delitem__(self, key):
        return self._layers.__delitem__(key)

    # Use the layer structure methods instead, they make more comprehensive changes (with metadata updates)
    def _append(self, layer):
        return self._layers.append(layer)

    def _remove(self,  layer):
        return self._layers.remove(layer)

    def _insert(self, index, layer):
        return self._layers.insert(index, layer)

    def _clear(self):
        return self._layers.clear()

    def _index(self, layer):
        return self._layers.index(layer)

    @deprecated
    def compose(
        self, force=False, bbox=None, layer_filter=None, context=None, color=None
    ):
        """
        Compose layer and masks (mask, vector mask, and clipping layers).

        :return: PIL Image object, or None if the layer has no pixels.
        """
        from psd_tools.composer import compose

        return compose(
            self,
            force=force,
            context=context,
            bbox=bbox,
            layer_filter=layer_filter,
            color=color,
        )

    def descendants(self, include_clip=True):
        """
        Return a generator to iterate over all descendant layers.

        Example::

            # Iterate over all layers
            for layer in psd.descendants():
                print(layer)

            # Iterate over all layers in reverse order
            for layer in reversed(list(psd.descendants())):
                print(layer)

        :param include_clip: include clipping layers.
        """
        for layer in self:
            yield layer
            if layer.is_group():
                for child in layer.descendants(include_clip):
                    yield child
            if include_clip and hasattr(layer, "clip_layers"):
                for clip_layer in layer.clip_layers:
                    yield clip_layer


class Group(GroupMixin, Layer):
    """
    Group of layers.

    Example::

        group = psd[1]
        for layer in group:
            if layer.kind == 'pixel':
                print(layer.name)
    """

    @staticmethod
    def extract_bbox(layers, include_invisible=False):
        """
        Returns a bounding box for ``layers`` or (0, 0, 0, 0) if the layers
        have no bounding box.

        :param include_invisible: include invisible layers in calculation.
        :return: tuple of four int
        """

        def _get_bbox(layer, **kwargs):
            if layer.is_group():
                return Group.extract_bbox(layer, **kwargs)
            else:
                return layer.bbox

        if not hasattr(layers, "__iter__"):
            layers = [layers]

        bboxes = [
            _get_bbox(layer, include_invisible=include_invisible)
            for layer in layers
            if include_invisible or layer.is_visible()
        ]
        bboxes = [bbox for bbox in bboxes if bbox != (0, 0, 0, 0)]
        if len(bboxes) == 0:  # Empty bounding box.
            return (0, 0, 0, 0)
        lefts, tops, rights, bottoms = zip(*bboxes)
        return (min(lefts), min(tops), max(rights), max(bottoms))

    def __init__(self, psd, record, channels, parent, _open_record = None, _open_channels = None):
        super(Group, self).__init__(psd, record, channels, parent)

        # Attributes that store the record for the folder divider. 
        # Used when updating the record so that we don't need to recompute 
        # Them from the ending layer 
        self._open_record = _open_record
        self._open_channels = _open_channels

        self._layers = []

    @property
    def _setting(self):
        # Can be None.
        return self.tagged_blocks.get_data(Tag.SECTION_DIVIDER_SETTING)

    @property
    def blend_mode(self):
        setting = self._setting
        if setting:
            return self._setting.blend_mode
        return super(Group, self).blend_mode

    @blend_mode.setter
    def blend_mode(self, value):
        _value = BlendMode(value)
        if _value == BlendMode.PASS_THROUGH:
            self._record.blend_mode = BlendMode.NORMAL
        else:
            self._record.blend_mode = _value
        setting = self._setting
        if setting:
            setting.blend_mode = _value

    def composite(
        self,
        viewport=None,
        force=False,
        color=1.0,
        alpha=0.0,
        layer_filter=None,
        apply_icc=False,
    ):
        """
        Composite layer and masks (mask, vector mask, and clipping layers).

        :param viewport: Viewport bounding box specified by (x1, y1, x2, y2)
            tuple. Default is the layer's bbox.
        :param force: Boolean flag to force vector drawing.
        :param color: Backdrop color specified by scalar or tuple of scalar.
            The color value should be in [0.0, 1.0]. For example, (1., 0., 0.)
            specifies red in RGB color mode.
        :param alpha: Backdrop alpha in [0.0, 1.0].
        :param layer_filter: Callable that takes a layer as argument and
            returns whether if the layer is composited. Default is
            :py:func:`~psd_tools.api.layers.PixelLayer.is_visible`.
        :return: :py:class:`PIL.Image`.
        """
        from psd_tools.composite import composite_pil

        return composite_pil(
            self,
            color,
            alpha,
            viewport,
            layer_filter,
            force,
            as_layer=True,
            apply_icc=apply_icc,
        )

    @classmethod
    def new(cls, name = "Group", open_folder = True):
        """
        Create a new Group object with minimal records and data channels and metadata to properly include the group in the PSD file.

        :param name: The display name of the group. Default to "Group".
        :param open_folder: Boolean defining whether the folder will be open or closed. Default to true.

        :return: A :py:class:`~psd_tools.api.layers.Group` object
        """

        record = LayerRecord(top=0, left=0, bottom=0, right=0, name=name)
        record.tagged_blocks = TaggedBlocks()

        record.tagged_blocks.set_data(Tag.SECTION_DIVIDER_SETTING, SectionDivider.OPEN_FOLDER if open_folder else SectionDivider.CLOSED_FOLDER)
        record.tagged_blocks.set_data(Tag.UNICODE_LAYER_NAME, name)


        _open_record = LayerRecord(top=0, left=0, bottom=0, right=0, name="</Layer group>")
        _open_record.tagged_blocks = TaggedBlocks()

        _open_record.tagged_blocks.set_data(Tag.SECTION_DIVIDER_SETTING, SectionDivider.BOUNDING_SECTION_DIVIDER)
        _open_record.tagged_blocks.set_data(Tag.UNICODE_LAYER_NAME, "</Layer group>")


        record.channel_info = [ChannelInfo(id=i-1, length = 2) for i in range(4)]
        _open_record.channel_info = [ChannelInfo(id=i-1, length = 2) for i in range(4)]


        channels = ChannelDataList()
        for i in range(4):
            channels.append(ChannelData(compression=Compression.RAW, data=b''))

        _open_channels = channels

        group = cls(None, record, channels, psd_file, _open_record, _open_channels)

        return group

    @classmethod
    def group_layers(cls, layers = [], name = "Group", parent = None, open_folder = True):
        """
        Create a new Group object containing the layers given in parameters.

        :param layers: The layers to group. Can by any subclass of :py:class:`~psd_tools.api.layers.Layer`
        :param name: The display name of the group. Default to "Group".
        :param parent: The parent group to add the newly created Group object into.
        :param open_folder: Boolean defining whether the folder will be open or closed. Default to true.

        :return: A :py:class:`~psd_tools.api.layers.Group` object
        """
        
        """If parent is none, the group will be placed in place of the first layer in the given list"""
        
        if not layers:
            return None

        if parent is None:
            parent = layers[0]._parent

        group = cls.new(name, open_folder)

        for layer in layers:
            layer.move_to_group(group)

        group.move_to_group(parent)

        return group


class Artboard(Group):
    """
    Artboard is a special kind of group that has a pre-defined viewbox.

    Example::

        artboard = psd[1]
        image = artboard.compose()
    """

    @classmethod
    def _move(kls, group):
        self = kls(group._psd, group._record, group._channels, group._parent)
        self._layers = group._layers
        for layer in self._layers:
            layer._parent = self
        for index in range(len(self.parent)):
            if group == self.parent[index]:
                self.parent._layers[index] = self
        return self

    @property
    def left(self):
        return self.bbox[0]

    @property
    def top(self):
        return self.bbox[1]

    @property
    def right(self):
        return self.bbox[2]

    @property
    def bottom(self):
        return self.bbox[3]

    @property
    def bbox(self):
        """(left, top, right, bottom) tuple."""
        if not hasattr(self, "_bbox"):
            data = None
            for key in (Tag.ARTBOARD_DATA1, Tag.ARTBOARD_DATA2, Tag.ARTBOARD_DATA3):
                if key in self.tagged_blocks:
                    data = self.tagged_blocks.get_data(key)
            assert data is not None
            rect = data.get(b"artboardRect")
            self._bbox = (
                int(rect.get(b"Left")),
                int(rect.get(b"Top ")),
                int(rect.get(b"Rght")),
                int(rect.get(b"Btom")),
            )
        return self._bbox

    def compose(self, bbox=None, **kwargs):
        """
        Compose the artboard.

        See :py:func:`~psd_tools.compose` for available extra arguments.

        :param bbox: Viewport tuple (left, top, right, bottom).
        :return: :py:class:`PIL.Image`, or `None` if there is no pixel.
        """
        from psd_tools.composer import compose

        return compose(self, bbox=bbox or self.bbox, **kwargs)


class PixelLayer(Layer):
    """
    Layer that has rasterized image in pixels.

    Example::

        assert layer.kind == 'pixel':
        image = layer.topil()
        image.save('layer.png')

        composed_image = layer.compose()
        composed_image.save('composed-layer.png')
    """

    @classmethod
    def frompil(cls, pil_im, layer_name = "Layer", top = 0, left = 0):
        """
        Method to create a layer from a PIL Image object, currently tuned for RGBA image.

        :param pil_im: The :py:class:`~PIL.Image` object to convert to photoshop
        :param layer_name: The name of the layer. Defaults to "Layer"
        :param top: Pixelwise offset from the top of the canvas for the new layer.
        :param left: Pixelwise offset from the left of the canvas for the new layer.

        :return: A :py:class:`~psd_tools.api.layers.PixelLayer` object

        TODO : Proper conversion check, other modes support        
        """

        layer_record = LayerRecord(top=top, left=left, bottom=top + pil_im.height, right=left + pil_im.width)

        layer_record.name = layer_name

        layer_record.channel_info = []
        channel_data_list = ChannelDataList()

        for channel in range(len(pil_im.getbands())):

            channel_data = ChannelData(compression=Compression.ZIP)
            channel_data.set_data(pil_im.getchannel(channel).tobytes(), pil_im.height, pil_im.width, 8)

            channel_data_list.append( channel_data )        
            
            c_info = ChannelInfo()
            c_info.length = len(channel_data.data) + 2

            if pil_im.getbands()[channel] == 'R':
                c_info.id = ChannelID.CHANNEL_0
            elif pil_im.getbands()[channel] == 'G':
                c_info.id = ChannelID.CHANNEL_1
            elif pil_im.getbands()[channel] == 'B':
                c_info.id = ChannelID.CHANNEL_2
            elif pil_im.getbands()[channel] == 'A':
                c_info.id = ChannelID.TRANSPARENCY_MASK

            layer_record.channel_info.append(c_info)

        self = cls(None, layer_record, channel_data_list, None)

        return self


class SmartObjectLayer(Layer):
    """
    Layer that inserts external data.

    Use :py:attr:`~psd_tools.api.layers.SmartObjectLayer.smart_object`
    attribute to get the external data. See
    :py:class:`~psd_tools.api.smart_object.SmartObject`.

    Example::

        import io
        if layer.smart_object.filetype == 'jpg':
            image = Image.open(io.BytesIO(layer.smart_object.data))
    """

    @property
    def smart_object(self):
        """
        Associated smart object.

        :return: :py:class:`~psd_tools.api.smart_object.SmartObject`.
        """
        if not hasattr(self, "_smart_object"):
            self._smart_object = SmartObject(self)
        return self._smart_object


class TypeLayer(Layer):
    """
    Layer that has text and styling information for fonts or paragraphs.

    Text is accessible at :py:attr:`~psd_tools.api.layers.TypeLayer.text`
    property. Styling information for paragraphs is in
    :py:attr:`~psd_tools.api.layers.TypeLayer.engine_dict`.
    Document styling information such as font list is is
    :py:attr:`~psd_tools.api.layers.TypeLayer.resource_dict`.

    Currently, textual information is read-only.

    Example::

        if layer.kind == 'type':
            print(layer.text)
            print(layer.engine_dict['StyleRun'])

            # Extract font for each substring in the text.
            text = layer.engine_dict['Editor']['Text'].value
            fontset = layer.resource_dict['FontSet']
            runlength = layer.engine_dict['StyleRun']['RunLengthArray']
            rundata = layer.engine_dict['StyleRun']['RunArray']
            index = 0
            for length, style in zip(runlength, rundata):
                substring = text[index:index + length]
                stylesheet = style['StyleSheet']['StyleSheetData']
                font = fontset[stylesheet['Font']]
                print('%r gets %s' % (substring, font))
                index += length
    """

    def __init__(self, *args):
        super(TypeLayer, self).__init__(*args)
        self._data = self.tagged_blocks.get_data(Tag.TYPE_TOOL_OBJECT_SETTING)

    @property
    def text(self):
        """
        Text in the layer. Read-only.

        .. note:: New-line character in Photoshop is `'\\\\r'`.
        """
        return self._data.text_data.get(b"Txt ").value.rstrip("\x00")

    @property
    def text_type(self):
        """
        Text type. Read-only.

        :return: 
         - :py:attr:`psd_tools.constants.TextType.POINT` for point type text (also known as character type)
         - :py:attr:`psd_tools.constants.TextType.PARAGRAPH` for paragraph type text (also known as area type)
         - `None` if text type cannot be determined or information is unavailable

        See :py:class:`psd_tools.constants.TextType`.
        """
        shapes = self._engine_data.get("EngineDict", {}).get("Rendered", {}).get("Shapes", {}).get("Children", {})
        if len(shapes) == 1:
            text_type = shapes[0].get("Cookie", {}).get("Photoshop", {}).get("ShapeType", {})
            if text_type in (0, 1):
                return TextType.POINT if text_type == 0 else TextType.PARAGRAPH
            else:
                logger.warning(f"Cannot determine text_type of layer '{self.name}' because information inside ShapeType was not found.")
                return None
        elif not shapes:
            logger.warning(f"Cannot determine text_type of layer '{self.name}' because information inside EngineDict was not found.")
            return None
        elif len(shapes) > 1:
            logger.warning(f"Cannot determine text_type of layer '{self.name}' because EngineDict has {len(shapes)} shapes.")
            return None

    @property
    def transform(self):
        """Matrix (xx, xy, yx, yy, tx, ty) applies affine transformation."""
        return self._data.transform

    @property
    def _engine_data(self):
        """Styling and resource information."""
        return self._data.text_data.get(b"EngineData").value

    @property
    def engine_dict(self):
        """Styling information dict."""
        return self._engine_data.get("EngineDict")

    @property
    def resource_dict(self):
        """Resource set."""
        return self._engine_data.get("ResourceDict")

    @property
    def document_resources(self):
        """Resource set relevant to the document."""
        return self._engine_data.get("DocumentResources")

    @property
    def warp(self):
        """Warp configuration."""
        return self._data.warp


class ShapeLayer(Layer):
    """
    Layer that has drawing in vector mask.
    """

    @property
    def left(self):
        return self.bbox[0]

    @property
    def top(self):
        return self.bbox[1]

    @property
    def right(self):
        return self.bbox[2]

    @property
    def bottom(self):
        return self.bbox[3]

    @property
    def bbox(self):
        """(left, top, right, bottom) tuple."""
        if not hasattr(self, "_bbox"):
            if self.has_pixels():
                self._bbox = (
                    self._record.left,
                    self._record.top,
                    self._record.right,
                    self._record.bottom,
                )
            elif self.has_origination() and not any(
                x.invalidated for x in self.origination
            ):
                lefts, tops, rights, bottoms = zip(*[x.bbox for x in self.origination])
                self._bbox = (
                    int(min(lefts)),
                    int(min(tops)),
                    int(max(rights)),
                    int(max(bottoms)),
                )
            elif self.has_vector_mask():
                bbox = self.vector_mask.bbox
                self._bbox = (
                    int(round(bbox[0] * self._psd.width)),
                    int(round(bbox[1] * self._psd.height)),
                    int(round(bbox[2] * self._psd.width)),
                    int(round(bbox[3] * self._psd.height)),
                )
            else:
                self._bbox = (0, 0, 0, 0)
        return self._bbox


class AdjustmentLayer(Layer):
    """Layer that applies specified image adjustment effect."""

    def __init__(self, *args):
        super(AdjustmentLayer, self).__init__(*args)
        self._data = None
        if hasattr(self.__class__, "_KEY"):
            self._data = self.tagged_blocks.get_data(self.__class__._KEY)

    def compose(self, **kwargs):
        """
        Adjustment layer is never composed.

        :return: None
        """
        return None


class FillLayer(Layer):
    """Layer that fills the canvas region."""

    def __init__(self, *args):
        super(FillLayer, self).__init__(*args)
        self._data = None
        if hasattr(self.__class__, "_KEY"):
            self._data = self.tagged_blocks.get_data(self.__class__._KEY)

    @property
    def left(self):
        return self._record.left

    @property
    def top(self):
        return self._record.top

    @property
    def right(self):
        return self._record.right or self._psd.width

    @property
    def bottom(self):
        return self._record.bottom or self._psd.height
