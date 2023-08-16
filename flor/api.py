from .constants import *
from . import cli
from . import utils
from . import versions
from . import obj_store

from typing import Any, Iterable, Iterator, TypeVar, Optional, Union
from contextlib import contextmanager

from tqdm import tqdm
import json
import atexit

import time
from datetime import datetime

T = TypeVar("T")

output_buffer = []

layers = {}
checkpoints = []

skip_cleanup = True


def log(name, value):
    if skip_cleanup:
        _deferred_init()

    serializable_value = value if utils.is_jsonable(value) else str(value)
    output_buffer.append(utils.add2copy(layers, name, serializable_value))
    tqdm.write(utils.to_string(layers, name, serializable_value))

    return value


def arg(name: str, default: Optional[Any] = None) -> Any:
    if cli.in_replay_mode():
        # GIT
        assert name in cli.flags.hyperparameters
        historical_v = cli.flags.hyperparameters[name]
        log(name, historical_v)
        return historical_v
    elif name in cli.flags.hyperparameters:
        # CLI
        v = cli.flags.hyperparameters[name]
        if default is not None:
            v = utils.duck_cast(v, default)
            log(name, v)
            return v
        log(name, v)
        return v
    elif default is not None:
        # default
        log(name, default)
        return default
    else:
        raise


@contextmanager
def checkpointing(**kwargs):
    # set up the context
    checkpoints.extend(list(kwargs.items()))
    yield
    # tear down the context if needed
    checkpoints.clear()


def loop(name: str, iterator: Iterable[T]) -> Iterator[T]:
    pos = len(layers)
    if pos == 0:
        output_buffer.append(
            utils.add2copy(
                layers,
                f"enter::{name}",
                datetime.now().isoformat(timespec="seconds"),
            )
        )
    layers[name] = 0
    for each in tqdm(
        slice(name, iterator), position=pos, leave=(True if pos == 0 else False)
    ):
        layers[name] = list(iterator).index(each) + 1 if pos == 0 else layers[name] + 1
        start_t = time.perf_counter()
        if pos == 0 and cli.in_replay_mode():
            load_chkpt()
        yield each
        elapsed_t = time.perf_counter() - start_t
        if pos == 0:
            output_buffer.append(utils.add2copy(layers, "auto::secs", elapsed_t))
            if is_due_chkpt(elapsed_t):
                chkpt()
    del layers[name]
    if pos == 0:
        output_buffer.append(
            utils.add2copy(
                layers,
                f"exit::{name}",
                datetime.now().isoformat(timespec="seconds"),
            )
        )


@atexit.register
def cleanup():
    if skip_cleanup:
        return
    if not cli.in_replay_mode():
        # RECORD
        branch = versions.current_branch()
        if branch is not None:
            output_buffer.append(
                {
                    "PROJID": PROJID,
                    "TSTAMP": TIMESTAMP,
                    "FILENAME": SCRIPTNAME,
                }
            )
            with open(".flor.json", "w") as f:
                json.dump(output_buffer, f, indent=2)
            versions.git_commit(f"FLOR::Auto-commit::{TIMESTAMP}")
    else:
        # REPLAY
        print("TODO: Add logging stmts to replay")


def _deferred_init():
    global skip_cleanup
    if skip_cleanup:
        skip_cleanup = False
        if not cli.in_replay_mode():
            assert (
                versions.current_branch() is not None
            ), "Running from a detached HEAD?"
            versions.to_shadow()


def is_due_chkpt(elapsed_t):
    return not cli.in_replay_mode()


def chkpt():
    for name, obj in checkpoints:
        output_buffer.append(
            utils.add2copy(
                layers,
                f"chkpt::{name}",
                obj_store.serialize(layers, name, obj),
            )
        )


def load_chkpt():
    for name, obj in checkpoints:
        obj_store.deserialize(layers, name, obj)


def slice(name, iterator):
    if not cli.in_replay_mode():
        return iterator

    assert cli.flags.queryparameters is not None
    qop = (cli.flags.queryparameters).get(name, 1)
    if qop == 1:
        return iterator

    new_slice = []
    if qop == 0:
        return new_slice

    original = list(iterator)
    assert isinstance(qop, (list, tuple))
    for i in qop:
        new_slice.append(original[int(i)])
    return new_slice


__all__ = ["log", "arg", "checkpointing", "loop"]
