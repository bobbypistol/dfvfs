# -*- coding: utf-8 -*-
"""The Volume Shadow Snapshots (VSS) file-like object implementation."""

import os

from dfvfs.file_io import file_io
from dfvfs.lib import errors
from dfvfs.lib import vshadow
from dfvfs.resolver import resolver


class VShadowFile(file_io.FileIO):
  """Class that implements a file-like object using pyvshadow."""

  def __init__(self, resolver_context):
    """Initializes the file-like object.

    Args:
      resolver_context: the resolver context (instance of resolver.Context).
    """
    super(VShadowFile, self).__init__(resolver_context)
    self._file_system = None
    self._vshadow_store = None

  def _Close(self):
    """Closes the file-like object.

    Raises:
      IOError: if the close failed.
    """
    self._vshadow_store = None

    self._file_system.Close()
    self._file_system = None

  def _Open(self, path_spec=None, mode='rb'):
    """Opens the file-like object defined by path specification.

    Args:
      path_spec: optional path specification (instance of path.PathSpec).
      mode: optional file access mode. The default is 'rb' read-only binary.

    Raises:
      AccessError: if the access to open the file was denied.
      IOError: if the file-like object could not be opened.
      PathSpecError: if the path specification is incorrect.
      ValueError: if the path specification is invalid.
    """
    if not path_spec:
      raise ValueError(u'Missing path specfication.')

    store_index = vshadow.VShadowPathSpecGetStoreIndex(path_spec)
    if store_index is None:
      raise errors.PathSpecError(
          u'Unable to retrieve store index from path specification.')

    self._file_system = resolver.Resolver.OpenFileSystem(
        path_spec, resolver_context=self._resolver_context)
    vshadow_volume = self._file_system.GetVShadowVolume()

    if (store_index < 0 or
        store_index >= vshadow_volume.number_of_stores):
      raise errors.PathSpecError((
          u'Unable to retrieve VSS store: {0:d} from path '
          u'specification.').format(store_index))

    self._vshadow_store = vshadow_volume.get_store(store_index)

  # Note: that the following functions do not follow the style guide
  # because they are part of the file-like object interface.

  def read(self, size=None):
    """Reads a byte string from the file-like object at the current offset.

       The function will read a byte string of the specified size or
       all of the remaining data if no size was specified.

    Args:
      size: Optional integer value containing the number of bytes to read.
            Default is all remaining data (None).

    Returns:
      A byte string containing the data read.

    Raises:
      IOError: if the read failed.
    """
    if not self._is_open:
      raise IOError(u'Not opened.')

    return self._vshadow_store.read(size)

  def seek(self, offset, whence=os.SEEK_SET):
    """Seeks an offset within the file-like object.

    Args:
      offset: The offset to seek.
      whence: Optional value that indicates whether offset is an absolute
              or relative position within the file. Default is SEEK_SET.

    Raises:
      IOError: if the seek failed.
    """
    if not self._is_open:
      raise IOError(u'Not opened.')

    self._vshadow_store.seek(offset, whence)

  def get_offset(self):
    """Returns the current offset into the file-like object.

    Raises:
      IOError: if the file-like object has not been opened.
    """
    if not self._is_open:
      raise IOError(u'Not opened.')

    return self._vshadow_store.get_offset()

  def get_size(self):
    """Returns the size of the file-like object.

    Raises:
      IOError: if the file-like object has not been opened.
    """
    if not self._is_open:
      raise IOError(u'Not opened.')

    return self._vshadow_store.volume_size
