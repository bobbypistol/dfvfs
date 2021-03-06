# -*- coding: utf-8 -*-
"""The compressed stream file-like object implementation."""

import os

from dfvfs.compression import manager as compression_manager
from dfvfs.file_io import file_io
from dfvfs.lib import errors
from dfvfs.resolver import resolver


class CompressedStream(file_io.FileIO):
  """Class that implements a file-like object of a compressed stream."""

  # The size of the compressed data buffer.
  _COMPRESSED_DATA_BUFFER_SIZE = 8 * 1024 * 1024

  def __init__(
      self, resolver_context, compression_method=None, file_object=None):
    """Initializes the file-like object.

    If the file-like object is chained do not separately use the parent
    file-like object.

    Args:
      resolver_context: the resolver context (instance of resolver.Context).
      compression_method: optional method used to the compress the data.
      file_object: optional parent file-like object.

    Raises:
      ValueError: if file_object provided but compression_method is not.
    """
    if file_object is not None and compression_method is None:
      raise ValueError(
          u'File-like object provided without corresponding compression '
          u'method.')

    super(CompressedStream, self).__init__(resolver_context)
    self._compression_method = compression_method
    self._file_object = file_object
    self._compressed_data = b''
    self._current_offset = 0
    self._decompressor = None
    self._realign_offset = True
    self._uncompressed_data = b''
    self._uncompressed_data_offset = 0
    self._uncompressed_data_size = 0
    self._uncompressed_stream_size = None

    if file_object:
      self._file_object_set_in_init = True
    else:
      self._file_object_set_in_init = False

  def _Close(self):
    """Closes the file-like object.

    If the file-like object was passed in the init function
    the compressed stream file-like object does not control
    the file-like object and should not actually close it.
    """
    if not self._file_object_set_in_init:
      self._file_object.close()
      self._file_object = None

    self._compressed_data = b''
    self._uncompressed_data = b''
    self._decompressor = None

  def _GetDecompressor(self):
    """Retrieves the decompressor."""
    return compression_manager.CompressionManager.GetDecompressor(
        self._compression_method)

  def _GetUncompressedStreamSize(self):
    """Retrieves the uncompressed stream size."""
    self._file_object.seek(0, os.SEEK_SET)

    self._decompressor = self._GetDecompressor()
    self._uncompressed_data = b''

    compressed_data_offset = 0
    compressed_data_size = self._file_object.get_size()
    uncompressed_stream_size = 0

    while compressed_data_offset < compressed_data_size:
      read_count = self._ReadCompressedData(self._COMPRESSED_DATA_BUFFER_SIZE)
      if read_count == 0:
        break

      compressed_data_offset += read_count
      uncompressed_stream_size += self._uncompressed_data_size

    return uncompressed_stream_size

  def _Open(self, path_spec=None, mode='rb'):
    """Opens the file-like object.

    Args:
      path_spec: optional path specification (instance of PathSpec).
      mode: optional file access mode. The default is 'rb' read-only binary.

    Raises:
      AccessError: if the access to open the file was denied.
      IOError: if the file-like object could not be opened.
      PathSpecError: if the path specification is incorrect.
      ValueError: if the path specification is invalid.
    """
    if not self._file_object_set_in_init and not path_spec:
      raise ValueError(u'Missing path specification.')

    if not self._file_object_set_in_init:
      if not path_spec.HasParent():
        raise errors.PathSpecError(
            u'Unsupported path specification without parent.')

      self._compression_method = getattr(path_spec, u'compression_method', None)

      if self._compression_method is None:
        raise errors.PathSpecError(
            u'Path specification missing compression method.')

      self._file_object = resolver.Resolver.OpenFileObject(
          path_spec.parent, resolver_context=self._resolver_context)

  def _AlignUncompressedDataOffset(self, uncompressed_data_offset):
    """Aligns the compressed file with the uncompressed data offset.

    Args:
      uncompressed_data_offset: the uncompressed data offset.
    """
    self._file_object.seek(0, os.SEEK_SET)

    self._decompressor = self._GetDecompressor()
    self._uncompressed_data = b''

    compressed_data_offset = 0
    compressed_data_size = self._file_object.get_size()

    while compressed_data_offset < compressed_data_size:
      read_count = self._ReadCompressedData(self._COMPRESSED_DATA_BUFFER_SIZE)
      if read_count == 0:
        break

      compressed_data_offset += read_count

      if uncompressed_data_offset < self._uncompressed_data_size:
        self._uncompressed_data_offset = uncompressed_data_offset
        break

      uncompressed_data_offset -= self._uncompressed_data_size

  def _ReadCompressedData(self, read_size):
    """Reads compressed data from the file-like object.

    Args:
      read_size: the number of bytes of compressed data to read.

    Returns:
      The number of bytes of compressed data read.
    """
    compressed_data = self._file_object.read(read_size)

    read_count = len(compressed_data)

    self._compressed_data = b''.join([self._compressed_data, compressed_data])

    self._uncompressed_data, self._compressed_data = (
        self._decompressor.Decompress(self._compressed_data))

    self._uncompressed_data_size = len(self._uncompressed_data)

    return read_count

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

    if self._current_offset < 0:
      raise IOError(
          u'Invalid current offset: {0:d} value less than zero.'.format(
              self._current_offset))

    if self._uncompressed_stream_size is None:
      self._uncompressed_stream_size = self._GetUncompressedStreamSize()

    if self._uncompressed_stream_size < 0:
      raise IOError(u'Invalid uncompressed stream size.')

    if self._current_offset >= self._uncompressed_stream_size:
      return b''

    if self._realign_offset:
      self._AlignUncompressedDataOffset(self._current_offset)
      self._realign_offset = False

    if size is None:
      size = self._uncompressed_stream_size
    if self._current_offset + size > self._uncompressed_stream_size:
      size = self._uncompressed_stream_size - self._current_offset

    uncompressed_data = b''

    if size == 0:
      return uncompressed_data

    while size > self._uncompressed_data_size:
      uncompressed_data = b''.join([
          uncompressed_data,
          self._uncompressed_data[self._uncompressed_data_offset:]])

      remaining_uncompressed_data_size = (
          self._uncompressed_data_size - self._uncompressed_data_offset)

      self._current_offset += remaining_uncompressed_data_size
      size -= remaining_uncompressed_data_size

      if self._current_offset >= self._uncompressed_stream_size:
        break

      read_count = self._ReadCompressedData(self._COMPRESSED_DATA_BUFFER_SIZE)
      self._uncompressed_data_offset = 0
      if read_count == 0:
        break

    if size > 0:
      slice_start_offset = self._uncompressed_data_offset
      slice_end_offset = slice_start_offset + size

      uncompressed_data = b''.join([
          uncompressed_data,
          self._uncompressed_data[slice_start_offset:slice_end_offset]])

      self._uncompressed_data_offset += size
      self._current_offset += size

    return uncompressed_data

  def seek(self, offset, whence=os.SEEK_SET):
    """Seeks an offset within the file-like object.

    Args:
      offset: the offset to seek.
      whence: optional value that indicates whether offset is an absolute
              or relative position within the file.

    Raises:
      IOError: if the seek failed.
    """
    if not self._is_open:
      raise IOError(u'Not opened.')

    if self._current_offset < 0:
      raise IOError(
          u'Invalid current offset: {0:d} value less than zero.'.format(
              self._current_offset))

    if whence == os.SEEK_CUR:
      offset += self._current_offset
    elif whence == os.SEEK_END:
      offset += self._uncompressed_stream_size
    elif whence != os.SEEK_SET:
      raise IOError(u'Unsupported whence.')
    if offset < 0:
      raise IOError(u'Invalid offset value less than zero.')

    if offset != self._current_offset:
      self._current_offset = offset
      self._realign_offset = True

  def get_offset(self):
    """Returns the current offset into the file-like object.

    Raises:
      IOError: if the file-like object has not been opened.
    """
    if not self._is_open:
      raise IOError(u'Not opened.')

    return self._current_offset

  def get_size(self):
    """Returns the size of the file-like object.

    Raises:
      IOError: if the file-like object has not been opened.
    """
    if not self._is_open:
      raise IOError(u'Not opened.')

    if self._uncompressed_stream_size is None:
      self._uncompressed_stream_size = self._GetUncompressedStreamSize()

    return self._uncompressed_stream_size
