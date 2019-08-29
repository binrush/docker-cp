# Script to copy files to and from docker container

Limitations:

  * requires python3.5+
  * only regular files are supported

## Installing dependencies

```
pip install -r requirements.txt
```

## Copy from container

```
python3 docker-cp.py <container>:<path-in-container> <local_destination>
```

## Copy to container

```
python3 docker-cp.py <local_source> <container>:<path-in-container>
```

## Running tests

```
py.test test_docker_cp.py
```
