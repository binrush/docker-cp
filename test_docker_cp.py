import os
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import pytest
import docker
from docker.errors import APIError

from docker_cp import _Reader, copy_from, CopyError, copy_to, copy


COPY_TO_DIR = '/tmp/test-copy-to'


def mock_generator():
    for _ in range(5):
        yield b'abc'


def test_reader():
    gen = mock_generator()
    reader = _Reader(gen)
    assert reader.read(1) == b'a'
    assert reader.read(2) == b'bc'
    assert reader.read(4) == b'abca'
    assert reader.read(7) == b'bcabcab'


@pytest.fixture(scope='module')
def test_container():
    client = docker.from_env()
    container = client.containers.run(
        'fedora:25', 'mkdir ' + COPY_TO_DIR, detach=True)
    yield container
    container.remove()
    client.close()


def test_copy_from(tmp_path, test_container):
    # copy non-existent file
    with pytest.raises(APIError):
        copy_from(test_container, '/etc/nonexistent', str(tmp_path))

    # copy file to directory
    tmp_path.joinpath('fedora-release').mkdir()
    with pytest.raises(CopyError) as exc_info:
        copy_from(test_container, '/etc/fedora-release', str(tmp_path))
    assert str(exc_info.value) == 'Destination is a directory'
    tmp_path.joinpath('fedora-release').rmdir()

    # Copy to non-existent directory
    with pytest.raises(CopyError) as exc_info:
        copy_from(test_container, '/etc/fedora-release',
                  str(tmp_path / 'test' / 'fr'))
    assert str(exc_info.value) == 'Not a directory: {}/test'.format(
        str(tmp_path))

    # Copying directory is not supported
    with pytest.raises(CopyError) as exc_info:
        copy_from(test_container, '/etc',
                  str(tmp_path / 'test' / 'fr'))
    assert str(exc_info.value) == 'Only regular files are supported'

    copy_from(test_container, '/etc/fedora-release', str(tmp_path))
    assert (tmp_path / 'fedora-release').open().read() == \
        'Fedora release 25 (Twenty Five)\n'

    copy_from(test_container, '/etc/fedora-release',
              str(tmp_path / 'tr'))
    assert (tmp_path / 'tr').open().read() == \
        'Fedora release 25 (Twenty Five)\n'


def test_copy_to(tmp_path, test_container):
    check_path = tmp_path.joinpath('check')
    check_path.mkdir()
    src1 = tmp_path.joinpath('src1')
    with src1.open(mode='w') as sf:
        sf.write('source1')

    # copy to directory
    copy_to(test_container, COPY_TO_DIR, str(src1))
    copy_from(
        test_container,
        os.path.join(COPY_TO_DIR, 'src1'),
        str(check_path))
    with (check_path / 'src1').open() as f:
        assert f.read() == 'source1'

    # overwrite existing file
    src2 = tmp_path.joinpath('src2')
    with src2.open(mode='w') as sf:
        sf.write('source2')
    dest = os.path.join(COPY_TO_DIR, 'src1')
    copy_to(test_container, dest, str(src2))
    copy_from(test_container, dest, str(check_path))
    with (check_path / 'src1').open() as f:
        assert f.read() == 'source2'


@pytest.fixture()
def mock_action(action):
    if action is None:
        yield
    else:
        with patch('docker_cp.' + action) as ma:
            yield ma


@pytest.mark.parametrize('bufsize, source, destination, action, retval', [
    [2, 'test:/etc/fedora-release', '/tmp', 'copy_from', 0],
    [2, '/etc/system-release', 'test:/tmp', 'copy_to', 0],
    [-2, '/etc/system-release', 'test:/tmp', None, 1],
    [2, '/etc/system-release', '/tmp', None, 1],
    [2, 'test1:/etc/system-release', 'test2:/tmp', None, 1],
])
def test_copy(bufsize, source, destination, mock_action, retval):
    args = Mock()
    args.buffer_length = bufsize
    args.source = source
    args.destination = destination
    with patch('docker_cp.docker'):
        assert copy(args) == retval
    if mock_action is not None:
        assert mock_action.called
