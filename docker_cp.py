import sys
import os
import tarfile
from argparse import ArgumentParser
from tempfile import TemporaryFile

import docker
from docker.errors import APIError

DEFAULT_BUF_SIZE = 1024
SEP = ':'

# ported from https://github.com/golang/go/blob/master/src/os/types.go
MODE_DIR = 1 << (32 - 1)
MODE_SYMLINK = 1 << (32 - 4)
MODE_DEV = 1 << (32 - 5)
MODE_NAMED_PIPE = 1 << (32 - 6)
MODE_SOCKET = 1 << (32 - 7)
MODE_CHAR_DEV = 1 << (32 - 10)
MODE_IRREGULAR = 1 << (32 - 12)
MODE_REG = (MODE_DIR | MODE_SYMLINK | MODE_NAMED_PIPE | MODE_SOCKET | MODE_DEV
            | MODE_CHAR_DEV | MODE_IRREGULAR)


def _is_dir(mode):
    return mode & MODE_DIR != 0


def _is_reg(mode):
    return mode & MODE_REG == 0


class CopyError(Exception):
    pass


class _Reader:
    def __init__(self, generator):
        self._generator = generator
        self._buf = b''

    def read(self, n):
        if len(self._buf) >= n:
            rv = self._buf[:n]
            self._buf = self._buf[n:]
        else:
            rv = self._buf
            self._buf = b''
            while len(rv) < n:
                try:
                    data = next(self._generator)
                except StopIteration:
                    break
                else:
                    to_return = n - len(rv)
                    rv += self._buf + data[:to_return]
                    self._buf = data[to_return:]
        return rv


def get_stat(container, path):
    """
    Get stat information for path in container
    Python api does not provide separate method to get stat
    information, using get_archive instead
    """
    data, st = container.get_archive(path)
    data.close()
    return st
            

def copy_from(container, path, dest):
    data, st = container.get_archive(path, chunk_size=DEFAULT_BUF_SIZE)
    try:
        if not _is_reg(st['mode']):
            raise CopyError("Only regular files are supported".format(path))
        with tarfile.open(
                fileobj=_Reader(data), bufsize=DEFAULT_BUF_SIZE, mode='r|') as tf:
            if os.path.isdir(dest):
                tf.extractall(path=dest)
                return
            parent = os.path.dirname(dest)
            if not os.path.isdir(parent):
                raise CopyError("Not a directory: " + parent)
            file_to_extract = tf.next()
            with open(dest, 'wb') as df, tf.extractfile(file_to_extract) as sf:
                while True:
                    chunk = sf.read(DEFAULT_BUF_SIZE)
                    if chunk:
                        df.write(chunk)
                    else:
                        break
    except IsADirectoryError:
        raise CopyError('Destination is a directory')
    finally:
        data.close()


def copy_to(container, path, src):
    if not os.path.isfile(src):
        raise CopyError("Not a file: {}".format(src))
    try:
        st = get_stat(container, path)
    except APIError:  # no such file or directory?
        # assume parent directory exists
        dest_dir = os.path.dirname(path)
        dest_file = os.path.basename(path)
    else:
        if _is_dir(st['mode']):
            dest_dir = path
            dest_file = os.path.basename(src)
        elif _is_reg(st['mode']):
            dest_dir = os.path.dirname(path)
            dest_file = os.path.basename(path)
        else:
            raise CopyError("Unable to overwrite {}".format(path))

    with TemporaryFile() as tempf:
        with tarfile.open(mode='w|', bufsize=DEFAULT_BUF_SIZE, fileobj=tempf) as tarf:
            tarf.add(src, arcname=dest_file)
        tempf.seek(0)
        container.put_archive(dest_dir, tempf)


def copy(args):
    if args.buffer_length <= 0:
        print("Buffer length should be positive integer")
        return 1
    src, dst = args.source, args.destination
    if (SEP in src) and (SEP not in dst):
        container_name, container_path = src.split(SEP, maxsplit=1)
        local_path = dst
        action = copy_from
    elif (SEP in dst) and (SEP not in src):
        container_name, container_path = dst.split(SEP, maxsplit=1)
        local_path = src
        action = copy_to
    else:
        print("Either source or destination should have format"
              "<container>:<path>")
        return 1
    try:
        client = docker.from_env()
        container = client.containers.get(container_name)
        action(container, container_path, local_path)
    except APIError as e:
        print("Docker API error: " + str(e))
        return 2
    except CopyError as e:
        print('Copy error: ' + str(e))
        return 2
    # Unknown errors are raised as is
    return 0


def main(args):
    parser = ArgumentParser(
        description='Copy files between docker container and local filesystem')
    parser.add_argument('source', type=str, help='Source file')
    parser.add_argument('destination', type=str, help='Destination file')
    parser.add_argument(
        '-b', '--buffer-length',
        type=int,
        required=False,
        default=DEFAULT_BUF_SIZE)

    args = parser.parse_args(args)
    exit(copy(args))


if __name__ == '__main__':
    main(sys.argv[1:])
