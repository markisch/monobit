"""
monobit.yaff - monobit-yaff and Unifont HexDraw formats

(c) 2019 Rob Hagemans
licence: https://opensource.org/licenses/MIT
"""

import logging
import string
from types import SimpleNamespace

from .text import clean_comment, write_comments, split_global_comment, to_text
from .typeface import Typeface
from .font import PROPERTIES, Font, Label
from .glyph import Glyph


_WHITESPACE = ' \t'
_CODESTART = _WHITESPACE + string.digits + string.ascii_letters + '_'


def draw_input_key(key):
    """Convert keys on input from .draw."""
    try:
        return int(key, 16)
    except (TypeError, ValueError):
        return Label(key)

def draw_output_key(key):
    """Convert keys on input from .draw."""
    try:
        return '{:04x}'.format(int(key))
    except ValueError:
        raise ValueError('.draw format only supports integer keys')


# defaults
_YAFF_PARAMETERS = dict(
    fore='@',
    back='.',
    comment='#',
    tab='    ',
    key_format=str,
    key_sep=':\n',
    empty='-',
)

_DRAW_PARAMETERS = dict(
    fore='#',
    back='-',
    comment='%',
    tab='\t',
    key_format=draw_output_key,
    key_sep=':',
    empty='-',
)


@Typeface.loads('yaff', 'text', 'txt', name='monobit-yaff')
def load(instream):
    """Read a plaintext font file."""
    fonts = []
    while True:
        font = _load_font(instream, fore='@', back='.', key_format=Label)
        if font is None:
            break
        fonts.append(font)
    if fonts:
        return Typeface(fonts)
    raise ValueError('No fonts found in file.')

@Typeface.saves('yaff', 'text', 'txt', multi=False)
def save(font, outstream):
    """Write fonts to a yaff file."""
    _save_yaff(font, outstream, **_YAFF_PARAMETERS)
    return font


@Typeface.loads('draw', name='hexdraw')
def load_draw(instream):
    """Read a hexdraw font file."""
    fonts = [_load_font(instream, fore='#', back='-', key_format=draw_input_key)]
    return Typeface(fonts)

@Typeface.saves('draw', multi=False)
def save_draw(font, outstream):
    """Write font to a hexdraw file."""
    _save_draw(font, outstream, **_DRAW_PARAMETERS)
    return font


##############################################################################
# read file

class Cluster(SimpleNamespace):
    """Bag of elements relating to one glyph."""

def new_cluster(**kwargs):
    return Cluster(
        labels=[],
        clusters=[],
        comments=[]
    )

def _is_glyph(value, fore, back):
    """Value is a glyph."""
    return not(set(value) - set(fore) - set(back))

def _load_font(instream, fore, back, key_format):
    """Read a plaintext font file."""
    global_comment = []
    current_comment = []
    # cluster by character
    elements = []
    for line in instream:
        if not line.rstrip('\r\n'):
            # preserve empty lines if they separate comments
            if current_comment and current_comment[-1] != '':
                current_comment.append('')
        elif line[0] not in _CODESTART:
            current_comment.append(line.rstrip('\r\n'))
        elif line[0] not in _WHITESPACE:
            # split out global comment
            if not elements:
                elements.append(new_cluster())
                if current_comment:
                    global_comm, current_comment = split_global_comment(current_comment)
                    global_comment.extend(global_comm)
            label, sep, rest = line.partition(':')
            if sep != ':':
                raise ValueError(f'Invalid yaff file: key `{label.strip()}` not followed by :')
            if elements[-1].clusters:
                # we already have stuff for the last key, so this is a new one
                elements.append(new_cluster())
            elements[-1].comments.extend(clean_comment(current_comment))
            current_comment = []
            elements[-1].labels.append(label)
            # remainder of label line after : is glyph row or property value
            rest = rest.strip()
            if rest:
                elements[-1].clusters.append(rest)
        else:
            elements[-1].clusters.append(line.strip())
    if not elements and not global_comment:
        # no font to read, no comments to keep
        return None
    # preserve any comment at end of file
    current_comment = clean_comment(current_comment)
    if current_comment:
        elements.append(new_cluster())
        elements[-1].comments = current_comment
    # properties: anything that contains more than .@
    property_elements = [
        _el for _el in elements
        if not _is_glyph(''.join(_el.clusters), fore, back)
    ]
    # multiple labels translate into multiple keys with the same value
    properties = {
        _key: '\n'.join(_el.clusters)
        for _el in property_elements
        for _key in _el.labels
    }
    # text version of glyphs
    # a glyph is any key/value where the value contains no alphanumerics
    glyph_elements = [
        _el for _el in elements
        if _is_glyph(''.join(_el.clusters), fore, back)
    ]
    labels = {
        key_format(_lab): _index
        for _index, _el in enumerate(glyph_elements)
        for _lab in _el.labels
    }
    # convert text representation to glyph
    glyphs = [
        (
            Glyph.from_matrix(_el.clusters, background=back).add_comments(_el.comments)
            if _el.clusters != ['-']
            else Glyph.empty().add_comments(_el.comments)
        )
        for _el in glyph_elements
    ]
    # extract property comments
    comments = {
        key_format(_key): _el.comments
        for _el in property_elements
        for _key in _el.labels
    }
    comments[None] = clean_comment(global_comment)
    return Font(glyphs, labels, comments, properties)


##############################################################################
# write file

def _write_glyph(outstream, labels, glyph, fore, back, comment, tab, key_format, key_sep, empty):
    """Write out a single glyph in text format."""
    if not labels:
        logging.warning('No labels for glyph: %s', glyph)
        return
    write_comments(outstream, glyph.comments, comm_char=comment)
    for ordinal in labels:
        outstream.write(key_format(ordinal) + key_sep)
    glyphtxt = to_text(glyph.as_matrix(fore, back), line_break='\n'+tab)
    # empty glyphs are stored as 0x0, not 0xm or nx0
    if not glyph.width or not glyph.height:
        glyphtxt = empty
    outstream.write(tab)
    outstream.write(glyphtxt)
    outstream.write('\n\n')

def _write_prop(outstream, key, value, tab):
    """Write out a property."""
    if value is None:
        return
    # this may use custom string converter (e.g ordinal labels)
    value = str(value)
    if not value:
        return
    if '\n' not in value:
        outstream.write('{}: {}\n'.format(key, value))
    else:
        outstream.write(
            ('{}:\n' + tab + '{}\n').format(
                key, ('\n' + tab).join(value.splitlines())
            )
        )

def _save_yaff(font, outstream, fore, back, comment, tab, key_format, key_sep, empty):
    """Write one font to a plaintext stream."""
    write_comments(outstream, font.get_comments(), comm_char=comment, is_global=True)
    props = {
        'name': font.name,
        'point-size': font.point_size,
        'spacing': font.spacing,
        **font.nondefault_properties
    }
    if props:
        for key in PROPERTIES:
            write_comments(outstream, font.get_comments(key), comm_char=comment)
            value = props.pop(key, '')
            _write_prop(outstream, key, value, tab)
        for key, value in props.items():
            write_comments(outstream, font.get_comments(key), comm_char=comment)
            _write_prop(outstream, key, value, tab)
        outstream.write('\n')
    for labels, glyph in font:
        _write_glyph(outstream, labels, glyph, fore, back, comment, tab, key_format, key_sep, empty)

def _save_draw(font, outstream, fore, back, comment, tab, key_format, key_sep, empty):
    """Write one font to a plaintext stream."""
    write_comments(outstream, font.get_comments(), comm_char=comment, is_global=True)
    for label, glyph in font.iter_unicode():
        if len(label.unicode) > 1:
            logging.warning("Can't encode grapheme cluster %s in .draw file; skipping.", str(label))
            continue
        _write_glyph(
            outstream, [ord(label.unicode)], glyph, fore, back, comment, tab, key_format, key_sep, empty
        )
