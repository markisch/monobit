"""
monobit.amiga - read Amiga font files

(c) 2019 Rob Hagemans
licence: https://opensource.org/licenses/MIT
"""

import os
import struct
import logging

from .base import VERSION, Font, ensure_stream


# amiga header constants
_MAXFONTPATH = 256
_MAXFONTNAME = 32

# hunk ids
# http://amiga-dev.wikidot.com/file-format:hunk
_HUNK_HEADER = 0x3f3
_HUNK_CODE = 0x3e9
_HUNK_RELOC32 = 0x3ec
_HUNK_END = 0x3f2


_FLAGS_MAP = {
    0x01: 'ROMFONT', # font is in rom
    0x02: 'DISKFONT', # font is from diskfont.library
    0x04: 'REVPATH', # This font is designed to be printed from from right to left
    0x08: 'TALLDOT', # This font was designed for a Hires screen (640x200 NTSC, non-interlaced)
    0x10: 'WIDEDOT', # This font was designed for a Lores Interlaced screen (320x400 NTSC)
    0x20: 'PROPORTIONAL', # character sizes can vary from nominal
    0x40: 'DESIGNED', # size explicitly designed, not constructed
    0x80: 'REMOVED', # the font has been removed
}


class _FileUnpacker:
    """Wrapper for struct.unpack."""

    def __init__(self, stream):
        """Start at start."""
        self._stream = stream
        self._offset = 0

    def unpack(self, format):
        """Read the next data specified by format string."""
        return struct.unpack(format, self._stream.read(struct.calcsize(format)))

    def read(self, n_bytes=-1):
        """Read number of raw bytes."""
        return self._stream.read(n_bytes)


def _read_ulong(f):
    """Read a 32-bit unsigned long."""
    return struct.unpack('>I', f.read(4))[0]

def _read_string(f):
    num_longs = _read_ulong(f)
    if num_longs < 1:
        return b''
    string = f.read(num_longs * 4)
    idx = string.find(b'\0')
    return string[:idx]

def _read_header(f):
    """Read file header."""
        # read header id
    if _read_ulong(f) != _HUNK_HEADER:
        raise ValueError('Not an Amiga font data file: incorrect magic constant')
    # null terminated list of strings
    library_names = []
    while True:
        s = _read_string(f)
        if not s:
            break
        library_names.append(s)
    table_size, first_slot, last_slot = struct.unpack('>III', f.read(12))
    # list of memory sizes of hunks in this file (in number of ULONGs)
    # this seems to exclude overhead, so not useful to determine disk sizes
    num_sizes = last_slot - first_slot + 1
    hunk_sizes = struct.unpack('>%dI' % (num_sizes,), f.read(4 * num_sizes))
    return library_names, table_size, first_slot, last_slot, hunk_sizes

def _read_font_hunk(f):
    """Parse the font data blob."""
    props = {
        'converter': 'monobit v{}'.format(VERSION),
        'source-name': '/'.join(f.name.split(os.sep)[-2:]),
        'source-format': 'Amiga',
    }
    # the file name tends to be the name as given in the .font anyway
    props['name'] = props['source-name']
    reader = _FileUnpacker(f)
    # number of longs in this hunk
    # ? apparently this is also ULONG dfh_NextSegment;
    # ? as per http://amigadev.elowar.com/read/ADCD_2.1/Libraries_Manual_guide/node05F9.html#line61
    num_longs, = reader.unpack('>I') # 4 bytes
    loc = f.tell()
    # immediate return code for accidental runs
    # this is ULONG dfh_ReturnCode;
    # MOVEQ  #-1,D0    ; Provide an easy exit in case this file is
    # RTS              ; "Run" instead of merely loaded.
    reader.unpack('>HH') # 2 statements: 4 bytes
    # struct Node
    # pln_succ, pln_pred, ln_type, ln_pri, pln_name
    reader.unpack('>IIBbI') # 14b
    # rev may be the revision number of the font
    # but name is only a placeholder, usually seems to be empty, but some of the bytes get used for versioning tags
    # fileid == 0f80, like a magic number for font files
    fileid, rev, seg, name = reader.unpack('>HHi%ds' % (_MAXFONTNAME,)) # 8+32b
    if b'\0' in name:
        name, name2 = name.split(b'\0', 1)
    if name:
        props['name'] = name.decode('latin-1')
    props['revision'] = rev
    # struct Message at start of struct TextFont
    # struct TextFont http://amigadev.elowar.com/read/ADCD_2.1/Libraries_Manual_guide/node03DE.html
    # struct Message http://amigadev.elowar.com/read/ADCD_2.1/Libraries_Manual_guide/node02EF.html
    # pln_succ, pln_pred, ln_type, ln_pri, pln_name, pmn_replyport, mn_length
    reader.unpack('>IIBbIIH') # 20b
    # font properties
    ysize, style, flags, xsize, baseline, boldsmear, accessors, lochar, hichar = reader.unpack('>HBBHHHHBB') #, f.read(2+2+4*2+2))
    props['bottom'] = -(ysize-baseline)
    props['size'] = ysize
    props['weight'] = 'bold' if style & 0x02 else 'medium'
    props['slant'] = 'italic' if style & 0x04 else 'roman'
    props['setwidth'] = 'expanded' if style & 0x08 else 'medium'
    proportional = bool(flags & 0x20)
    props['spacing'] = 'proportional' if proportional else 'monospace'
    flag_tags = ' '.join(tag for mask, tag in _FLAGS_MAP.items() if flags & mask)
    # preserve unparsed properties
    if style & 0x01:
        props['_STYLE'] = 'UNDERLINED'
    # tf_BoldSmear; /* smear to affect a bold enhancement */
    props['_BOLDSMEAR'] = boldsmear
    # preserve tags stored in name field after \0
    if name2:
        props['_TAG'] = name2.replace(b'\0', b'').decode('latin-1')
    # preserve unparsed flags
    if flag_tags:
        props['_FLAGS'] = flag_tags
    # data structure parameters
    tf_chardata, tf_modulo, tf_charloc, tf_charspace, tf_charkern = reader.unpack('>IHIII') #, f.read(18))
    # char data
    f.seek(tf_chardata+loc, 0)
    #assert f.tell() - loc == tf_chardata
    rows = [
        ''.join(
            '{:08b}'.format(_c)
            for _c in reader.read(tf_modulo)
        )
        for _ in range(ysize)
    ]
    rows = [
        [
            _c != '0'
            for _c in _row
        ]
        for _row in rows
    ]
    # location data
    f.seek(tf_charloc+loc, 0)
    #assert f.tell() - loc == tf_charloc
    nchars = hichar - lochar + 1 + 1 # one additional glyph at end for undefined chars
    locs = [reader.unpack('>HH') for  _ in range(nchars)]
    # spacing data, can be negative
    f.seek(tf_charspace+loc, 0)
    #assert f.tell() - loc == tf_charspace
    spacing = reader.unpack('>%dh' % (nchars,))
    # kerning data, can be negative
    f.seek(tf_charkern+loc, 0)
    #assert f.tell() - loc == tf_charkern
    kerning = reader.unpack('>%dh' % (nchars,))
    #assert reader.unpack('>H') == (0,)
    #assert f.tell() - loc == num_longs*4
    # apparently followed by _HUNK_RELOC32 and _HUNK_END
    font = [
        [_row[_offs: _offs+_width] for _row in rows]
        for _offs, _width in locs
    ]
    # apply spacing
    if proportional:
        for i, sp in enumerate(spacing):
            if sp < 0:
                logging.warning('negative spacing in %dth character' % (i,))
            if abs(sp) > xsize*2:
                logging.error('very high values in spacing table')
                spacing = (xsize,) * len(font)
                break
    else:
        spacing = (xsize,) * len(font)
    for i, sp in enumerate(kerning):
        if sp < 0:
            logging.warning('negative kerning in %dth character' % (i,))
        if abs(sp) > xsize*2:
            logging.error('very high values in kerning table')
            kerning = (0,) * len(font)
            break
    font = [
        [[False] * _kern + _row + [False] * (_width - _kern - len(_row)) for _row in _char]
        for _char, _width, _kern in zip(font, spacing, kerning)
    ]
    glyphs = dict(enumerate(font, lochar))
    # default glyph doesn't have an encoding value
    default = max(glyphs)
    glyphs['default'] = glyphs[default]
    del glyphs[default]
    props['default-char'] = 'default'
    return Font(glyphs, properties=props)


@Font.loads('amiga')
def load(f):
    """Read Amiga disk font file."""
    with ensure_stream(f, 'rb'):
        # read & ignore header
        _read_header(f)
        if _read_ulong(f) != _HUNK_CODE:
            raise ValueError('Not an Amiga font data file: no code hunk found (id %04x)' % hunk_id)
        return _read_font_hunk(f)
