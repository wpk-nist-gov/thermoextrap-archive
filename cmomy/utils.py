"""Utilities."""
from __future__ import annotations

from functools import lru_cache
from typing import Sequence, Tuple

import numpy as np
import xarray as xr
from numba import njit
from numpy.typing import ArrayLike, DTypeLike

from ._typing import ASARRAY_ORDER

# from .cached_decorators import gcached  # , cached_clear
from .options import OPTIONS


def myjit(func):
    """Jitter with option inline='always', fastmath=True."""
    return njit(inline="always", fastmath=OPTIONS["fastmath"], cache=OPTIONS["cache"])(
        func
    )


# from scipy.special import binom
# def factory_binomial(order):
#     irange = np.arange(order + 1)
#     bfac = np.array([binom(i, irange) for i in irange])
#     return bfac


def _binom(n, k):
    if n > k:
        return np.math.factorial(n) / (np.math.factorial(k) * np.math.factorial(n - k))
    elif n == k:
        return 1.0
    else:
        # n < k
        return 0.0


def factory_binomial(order: int, dtype: DTypeLike = float):
    """Create binomial coefs at given order."""
    out = np.zeros((order + 1, order + 1), dtype=dtype)
    for n in range(order + 1):
        for k in range(order + 1):
            out[n, k] = _binom(n, k)

    return out


# def _my_broadcast(x, shape, dtype=None, order=None):
#     x = np.asarray(x, dtype=dtype, order=order)
#     if x.shape != shape:
#         x = np.broadcast(x, shape)
#     return x


def _shape_insert_axis(
    shape: Sequence[int], axis: int | None, new_size: int
) -> Tuple[int, ...]:
    """Get new shape, given shape, with size put in position axis."""
    if axis is None:
        raise ValueError("must specify integre axis")

    axis = np.core.numeric.normalize_axis_index(axis, len(shape) + 1)  # type: ignore
    shape = tuple(shape)
    return shape[:axis] + (new_size,) + shape[axis:]


def _shape_reduce(shape: Tuple[int, ...], axis: int) -> Tuple[int, ...]:
    """Give shape shape after reducing along axis."""
    shape_list = list(shape)
    shape_list.pop(axis)
    return tuple(shape_list)


def _axis_expand_broadcast(
    x: ArrayLike,
    shape: Tuple[int, ...],
    axis: int | None,
    verify: bool = True,
    expand: bool = True,
    broadcast: bool = True,
    roll: bool = True,
    dtype: DTypeLike | None = None,
    order: ASARRAY_ORDER = None,
) -> np.ndarray:
    """Broadcast x to shape.

    If x is 1d, and shape is n-d, but len(x) is same as shape[axis],
    broadcast x across all dimensions
    """

    if verify is True:
        x = np.asarray(x, dtype=dtype, order=order)
    else:
        assert isinstance(x, np.ndarray)

    # if array, and 1d with size same as shape[axis]
    # broadcast from here
    if expand:
        # assert axis is not None
        if x.ndim == 1 and x.ndim != len(shape):
            if axis is None:
                raise ValueError("trying to expand an exis with axis==None")
            if len(x) == shape[axis]:
                # reshape for broadcasting
                reshape = (1,) * (len(shape) - 1)
                reshape = _shape_insert_axis(reshape, axis, -1)
                x = x.reshape(*reshape)

    if broadcast and x.shape != shape:
        x = np.broadcast_to(x, shape)
    if roll and axis is not None and axis != 0:
        x = np.moveaxis(x, axis, 0)
    return x


@lru_cache(maxsize=5)
def _cached_ones(shape, dtype=None):
    return np.ones(shape, dtype=dtype)


def _xr_wrap_like(da, x):
    """Wrap x with xarray like da."""
    x = np.asarray(x)
    assert x.shape == da.shape

    return xr.DataArray(
        x, dims=da.dims, coords=da.coords, name=da.name, indexes=da.indexes
    )


def _xr_order_like(template, *others):
    """Given dimensions, order in same manner."""

    if not isinstance(template, xr.DataArray):
        out = others

    else:
        dims = template.dims

        key_map = {dim: i for i, dim in enumerate(dims)}

        def key(x):
            return key_map[x]

        out = []
        for other in others:
            if isinstance(other, xr.DataArray):
                # reorder
                order = sorted(other.dims, key=key)

                x = other.transpose(*order)
            else:
                x = other

            out.append(x)

    if len(out) == 1:
        out = out[0]

    return out
