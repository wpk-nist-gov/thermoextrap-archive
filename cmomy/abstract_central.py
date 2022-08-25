# type: ignore
# flake8: noqa
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import (
    Any,
    Generic,
    Hashable,
    Literal,
    Mapping,
    Sequence,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    no_type_check,
)

import numpy as np
import xarray as xr
from numpy.core.numeric import normalize_axis_index  # type: ignore
from numpy.typing import ArrayLike, DTypeLike

from . import convert
from ._typing import ASARRAY_ORDER, T_MOM
from .cached_decorators import gcached
from .pushers import factory_pushers
from .resample import randsamp_freq, resample_data, resample_vals
from .utils import _axis_expand_broadcast  # _cached_ones,; _my_broadcast,
from .utils import _shape_insert_axis, _shape_reduce

T_CENTRALMOMENTS = TypeVar("T_CENTRALMOMENTS", bound="CentralMomentsABC")
T_npxr_strict = Union[np.ndarray, xr.DataArray]
T_npxr_like = Union[ArrayLike, xr.DataArray]


T_array = TypeVar("T_array_output", np.ndarray, xr.DataArray)

# TODO: Total rework is called for to handle typing correctly.
# instead of xCentral subclassing Central, these should be separate things
# for the cases where things are in the wrong format, can create a Central object,
# then convert to an xCentral object


class CentralMomentsABC(ABC, Generic[T_array]):
    @abstractmethod
    def __init__(self, data: T_array, mom_ndims: int = 1) -> None:
        pass

    @property
    def data(self) -> np.ndarray:
        """Accessor to numpy underlying data.

        By convention data has the following meaning for the moments indexes

        * `data[...,i=0,j=0]`, weights
        * `data[...,i=1,j=0]]`, if only one moment indice is one and all
        others zero, then this is the average value of the variable with unit index.

        * all other cases, the central moments `<(x0-<x0>)**i0 * (x1 - <x1>)**i1 * ...>`
        """
        return self._data

    @property
    @abstractmethod
    def values(self) -> T_array:
        pass

    @property
    def shape(self) -> Tuple[int, ...]:
        """self.data.shape."""
        return self.data.shape

    @property
    def ndim(self) -> int:
        """self.data.ndim."""
        return self.data.ndim

    @property
    def dtype(self):
        """self.data.dtype."""
        return self.data.dtype

    @property
    def mom_ndim(self) -> Literal[1, 2]:
        """Length of moments.

        if `mom_ndim` == 1, then single variable
        moments if `mom_ndim` == 2, then co-moments.
        """
        return self._mom_ndim  # type: ignore

    @property
    def mom_shape(self) -> Tuple[int] | Tuple[int, int]:
        """Shape of moments part."""
        return self.data.shape[-self.mom_ndim :]  # type: ignore

    @property
    def mom(self) -> Tuple[int] | Tuple[int, int]:
        """Number of moments."""  # noqa D401
        return tuple(x - 1 for x in self.mom_shape)  # type: ignore

    @property
    def val_shape(self) -> Tuple[int, ...]:
        """Shape of values dimensions.

        That is shape less moments dimensions.
        """
        return self.data.shape[: -self.mom_ndim]

    @property
    def val_ndim(self) -> int:
        """Number of value dimensions."""  # noqa D401
        return len(self.val_shape)

    @property
    def val_shape_flat(self) -> Tuple[int, ...]:
        """Shape of values part flattened."""
        if self.val_shape == ():
            return ()
        else:
            return (np.prod(self.val_shape),)

    @property
    def shape_flat(self) -> Tuple[int, ...]:
        """Shape of flattened data."""
        return self.val_shape_flat + self.mom_shape

    @property
    def mom_shape_var(self) -> Tuple[int, ...]:
        """Shape of moment part of variance."""
        return tuple(x - 1 for x in self.mom)

    @property
    def shape_var(self) -> Tuple[int, ...]:
        """Total variance shape."""
        return self.val_shape + self.mom_shape_var

    @property
    def shape_flat_var(self) -> Tuple[int, ...]:
        """Shape of flat variance."""
        return self.val_shape_flat + self.mom_shape_var

    # I think this is for pickling
    # probably don't need it anymore
    # def __setstate__(self, state):
    #     self.__dict__ = state
    #     # make sure datar points to data
    #     self._data_flat = self._data.reshape(self.shape_flat)

    # not sure I want to actually implements this
    # could lead to all sorts of issues applying
    # ufuncs to underlying data
    # def __array_wrap__(self, obj, context=None):
    #     return self, obj, context

    @gcached()
    def _push(self):
        vec = len(self.val_shape) > 0
        cov = self.mom_ndim == 2
        return factory_pushers(cov=cov, vec=vec)

    def __repr__(self):
        """Repr for class."""
        name = self.__class__.__name__
        s = f"<{name}(val_shape={self.val_shape}, mom={self.mom})>\n"
        return s + repr(self.values)

    def __array__(self, dtype: DTypeLike | None = None) -> np.ndarray:
        """Used by np.array(self)."""  # noqa D401
        return np.asarray(self.data, dtype=dtype)

    ###########################################################################
    # SECTION: top level creation/copy/new
    ###########################################################################
    @abstractmethod
    def new_like(
        self: T_CENTRALMOMENTS,
        *,
        data: T_npxr_like | None = None,
        copy: bool = False,
        copy_kws: Mapping | None = None,
        verify: bool = True,
        check_shape: bool = True,
        strict: bool = False,
        **kws,
    ) -> T_CENTRALMOMENTS:
        """Create new object like self, with new data.

        Parameters
        ----------
        data : array-like, optional
            data for new object
        verify : bool, default=False
            if True, pass data through np.asarray
        check : bool, default=True
            if True, then check that data has same total shape as self
        copy : bool, default=False
            if True, perform copy of data
        copy_kws : dict, optional
            key-word arguments to `self.data.copy`
        **kws : extra arguments
            arguments to classmethod `from_data`
        """

    def zeros_like(self: T_CENTRALMOMENTS) -> T_CENTRALMOMENTS:
        """Create new object empty object like self."""
        return self.new_like()

    def copy(self: T_CENTRALMOMENTS, **copy_kws) -> T_CENTRALMOMENTS:
        """Create a new object with copy of data."""
        return self.new_like(
            data=self.values,
            verify=False,
            check_shape=False,
            copy=True,
            copy_kws=copy_kws,
        )

    @classmethod
    @abstractmethod
    def zeros(
        cls: Type[T_CENTRALMOMENTS],
        mom: T_MOM | None = None,
        val_shape: Tuple[int, ...] | None = None,
        mom_ndim: int | None = None,
        shape: Tuple[int, ...] | None = None,
        dtype: DTypeLike | None = None,
        zeros_kws: Mapping | None = None,
        **kws,
    ) -> T_CENTRALMOMENTS:
        """Create a new base object.

        Parameters
        ----------
        mom : int or tuple
            moments.
            if integer, or length one tuple, then moments of single variable.
            if tuple of length 2, then comoments of two variables.
        val_shape : tuple, optional
            shape of values, excluding moments.  For example, if considering the average
            of observations `x`, then `val_shape = x.shape`
            if not passed, then assume val_shape = ()
        shape : tuple, optional
            if passed, create object with this total shape
        mom_ndim : int {1, 2}, optional
            number of variables.
            if pass `shape`, then must pass mom_ndim
        dtype : nunpy dtype, default=float

        **kws : dict
            extra arguments to cls.from_data

        Returns
        -------
        object : instance of class `cls`

        Notes
        -----
        the resulting total shape of data is shape + (mom + 1)
        """
        pass

    ###########################################################################
    # SECTION: Access to underlying statistics
    ###########################################################################
    @gcached()
    def _weight_index(self) -> Tuple[int, ...]:
        index = (0,) * len(self.mom)
        if self.val_ndim > 0:
            index = (...,) + index
        return index

    @gcached(prop=False)
    def _single_index(self, val) -> Tuple[List[int], ...]:
        # index with things like data[..., 1,0] data[..., 0,1]
        # index = (...,[1,0],[0,1])
        dims = len(self.mom)
        if dims == 1:
            index = [val]
        else:
            # this is a bit more complicated
            index = [[0] * dims for _ in range(dims)]
            for i in range(dims):
                index[i][i] = val

        if self.val_ndim > 0:
            index = [...] + index

        return tuple(index)

    def weight(self) -> float | T_array:
        """Weight data."""
        return self.values[self._weight_index]

    def mean(self) -> float | T_array:
        """Mean (first moment)."""
        return self.values[self._single_index(1)]

    def var(self) -> float | T_array:
        """Variance (second central moment)."""
        return self.values[self._single_index(2)]

    def std(self) -> float | T_array:
        """Standard deviation."""  # noqa D401
        return np.sqrt(self.var())

    def cmom(self) -> T_array:
        """Central moments.

        cmom[..., i0, i1] = < (x0 - <x0>)**i0 * (x1 - <x1>)**i1>
        Note that this is scrict, so `cmom[..., i, j] = 0` if `i+j = 0`
        and `cmom[...,0, 0] = 1`.

        """
        out = self.data.copy()
        # zeroth central moment
        out[self._weight_index] = 1
        # first central moment
        out[self._single_index(1)] = 0
        return out

    def to_raw(self) -> T_array:
        """Convert central moments to raw moments.

        raw[...,i, j] = weight,           i = j = 0
                      = <x0**i * x1**j>,  otherwise
        """
        if self.mom_ndim == 1:
            return convert.to_raw_moments(x=self.data)
        elif self.mom_ndim == 2:
            return convert.to_raw_comoments(x=self.data)

    def rmom(self) -> T_array:
        """Raw moments.

        rmom[..., i, j] = <x0 ** i * x1 ** j>
        """
        out = self.to_raw()
        out[self._weight_index] = 1
        return out

    ###########################################################################
    # SECTION: pushing routines
    ###########################################################################
    def fill(self: T_CENTRALMOMENTS, value: Any = 0) -> T_CENTRALMOMENTS:
        """Fill data with value."""
        self._data.fill(value)
        return self

    def zero(self: T_CENTRALMOMENTS) -> T_CENTRALMOMENTS:
        """Zero out underlying data."""
        return self.fill(value=0.0)

    @abstractmethod
    def _verify_value(
        self,
        x: Any,
        target: any,
        axis: int | None = None,
        broadcast: bool = False,
        expand: bool = False,
        other: Any | None = None,
        *args,
        **kwargs,
    ):
        pass

    def _check_weight(self, w, target, **kwargs):  # type: ignore
        if w is None:
            w = 1.0
        return self._verify_value(
            w,
            target=target,
            broadcast=True,
            expand=True,
            shape_flat=self.val_shape_flat,
            **kwargs,
        )

    def _check_weights(
        self,
        w,
        target,
        axis: int = None,
        **kwargs,
    ):
        # type: ignore
        if w is None:
            w = 1.0
        return self._verify_value(
            w,
            target=target,
            axis=axis,
            broadcast=True,
            expand=True,
            shape_flat=self.val_shape_flat,
            **kwargs,
        )

    def _check_val(self, x, target, broadcast=False, **kwargs):  # type: ignore
        return self._verify_value(
            x,
            target=target,
            broadcast=broadcast,
            expand=False,
            shape_flat=self.val_shape_flat,
            **kwargs,
        )

    def _check_vals(self, x, target, axis, broadcast=False, **kwargs):  # type: ignore
        return self._verify_value(
            x,
            target=target,
            axis=axis,
            broadcast=broadcast,
            expand=broadcast,
            shape_flat=self.val_shape_flat,
            **kwargs,
        )

    def _check_var(self, v, broadcast=False, **kwargs):
        return self._verify_value(
            v,
            target="var",  # self.shape_var,
            broadcast=broadcast,
            expand=False,
            shape_flat=self.shape_flat_var,
            **kwargs,
        )[0]

    def _check_vars(
        self, v, target, axis, broadcast: bool = False, **kwargs
    ):  # type: ignore
        return self._verify_value(
            v,
            target="vars",
            axis=axis,
            broadcast=broadcast,
            expand=broadcast,
            shape_flat=self.shape_flat_var,
            other=target,
            **kwargs,
        )[0]

    def _check_data(self, data, **kwargs):  # type: ignore
        return self._verify_value(
            data, target="data", shape_flat=self.shape_flat, **kwargs
        )[0]

    def _check_datas(self, datas, axis, **kwargs):  # type: ignore
        return self._verify_value(
            datas,
            target="datas",
            axis=axis,
            shape_flat=self.shape_flat,
            **kwargs,
        )[0]

    def push_data(self: T_CENTRALMOMENTS, data: Any) -> T_CENTRALMOMENTS:
        """Push data object to moments.

        Parameters
        ----------
        data : array-like, `shape=self.shape`
            array storing moment information
        Returns
        -------
        self

        See Also
        --------
        cmomy.CentralMoments.data
        """
        data = self._check_data(data)
        self._push.data(self._data_flat, data)
        return self

    def push_datas(
        self: T_CENTRALMOMENTS,
        datas,
        axis: int,
        **kwargs,
    ) -> T_CENTRALMOMENTS:
        """Push and reduce multiple average central moments.

        Parameters
        ----------
        datas : array-like
            this should have shape like `(nrec,) + self.shape`
            if `axis=0`, where `nrec` is the number of data objects to sum.
        axis : int
            axis to reduce along

        Returns
        -------
        self
        """

        datas = self._check_datas(datas=datas, axis=axis, **kwargs)
        self._push.datas(self._data_flat, datas)
        return self

    def push_val(
        self: T_CENTRALMOMENTS, x, w=None, broadcast: bool = False, **kwargs
    ) -> T_CENTRALMOMENTS:
        """Push single sample to central moments.

        Parameters
        ----------
        x : array-like or tuple of arrays
            if `self.mom_ndim == 1`, then this is the value to consider
            if `self.mom_ndim == 2`, then `x = (x0, x1)`
            `x.shape == self.val_shape`

        w : int, float, array-like, optional
            optional weight of each sample
        broadcast : bool, default = False
            If true, do smart broadcasting for `x[1:]`

        Returns
        -------
        self
        """

        if self.mom_ndim == 1:
            ys = ()
        else:
            assert isinstance(x, tuple) and len(x) == self.mom_ndim
            x, *ys = x  # type: ignore

        xr, target = self._check_val(x, "val", **kwargs)  # type: ignore
        yr = tuple(self._check_val(y, target=target, broadcast=broadcast) for y in ys)  # type: ignore
        wr = self._check_weight(w, target)  # type: ignore
        self._push.val(self._data_flat, *((wr, xr) + yr))
        return self

    def push_vals(
        self: T_CENTRALMOMENTS,
        x,
        w=None,
        axis: int | None = None,
        broadcast: bool = False,
        **kwargs,
    ) -> T_CENTRALMOMENTS:
        """Push multiple samples to central moments.

        Parameters
        ----------
        x : array-like or tuple of arrays
            if `self.mom_ndim` == 1, then this is the value to consider
            if `self.mom_ndim` == 2, then x = (x0, x1)
            `x.shape[:axis] + x.shape[axis+1:] == self.val_shape`

        w : int, float, array-like, optional
            optional weight of each sample
        axis : int, default=0
            axis to reduce along
        broadcast : bool, default = False
            If true, do smart broadcasting for `x[1:]`
        """
        if self.mom_ndim == 1:
            ys = ()
        else:
            assert len(x) == self.mom_ndim
            x, *ys = x  # type: ignore

        xr, target = self._check_vals(x, axis=axis, target="vals", **kwargs)  # type: ignore
        yr = tuple(  # type: ignore
            self._check_vals(y, target=target, axis=axis, broadcast=broadcast, **kwargs)  # type: ignore
            for y in ys  # type: ignore
        )  # type: ignore
        wr = self._check_weights(w, target=target, axis=axis, **kwargs)
        self._push.vals(self._data_flat, *((wr, xr) + yr))
        return self

    ###########################################################################
    # SECTION: Operators
    ###########################################################################
    def _check_other(self: T_CENTRALMOMENTS, b: T_CENTRALMOMENTS) -> None:
        """Check other object."""
        assert type(self) == type(b)
        assert self.mom_ndim == b.mom_ndim
        assert self.shape == b.shape

    def __iadd__(
        self: T_CENTRALMOMENTS,
        b: T_CENTRALMOMENTS,
    ) -> T_CENTRALMOMENTS:  # noqa D105
        self._check_other(b)
        # self.push_data(b.data)
        # return self
        return self.push_data(b.data)

    def __add__(
        self: T_CENTRALMOMENTS,
        b: T_CENTRALMOMENTS,
    ) -> T_CENTRALMOMENTS:
        """Add objects to new object."""
        self._check_other(b)
        # new = self.copy()
        # new.push_data(b.data)
        # return new
        return self.copy().push_data(b.data)

    def __isub__(
        self: T_CENTRALMOMENTS,
        b: T_CENTRALMOMENTS,
    ) -> T_CENTRALMOMENTS:
        """Inplace substraction."""
        # NOTE: consider implementint push_data_scale routine to make this cleaner
        self._check_other(b)
        assert np.all(self.weight() >= b.weight())
        data = b.data.copy()
        data[self._weight_index] *= -1
        # self.push_data(data)
        # return self
        return self.push_data(data)

    def __sub__(
        self: T_CENTRALMOMENTS,
        b: T_CENTRALMOMENTS,
    ) -> T_CENTRALMOMENTS:
        """Subtract objects."""
        self._check_other(b)
        assert np.all(self.weight() >= b.weight())
        new = b.copy()
        new._data[self._weight_index] *= -1
        # new.push_data(self.data)
        # return new
        return new.push_data(self.data)

    def __mul__(self: T_CENTRALMOMENTS, scale: float | int) -> T_CENTRALMOMENTS:
        """New object with weights scaled by scale."""  # noqa D401
        scale = float(scale)
        new = self.copy()
        new._data[self._weight_index] *= scale
        return new

    def __imul__(self: T_CENTRALMOMENTS, scale: float | int) -> T_CENTRALMOMENTS:
        """Inplace multiply."""
        scale = float(scale)
        self._data[self._weight_index] *= scale
        return self

    ###########################################################################
    # SECTION: Constructors
    ###########################################################################
    @classmethod
    @no_type_check
    def _check_mom(
        cls, moments: T_MOM, mom_ndim: int, shape: Tuple[int, ...] | None = None
    ) -> Union[Tuple[int], Tuple[int, int]]:  # type: ignore
        """Check moments for correct shape.

        If moments is None, infer from
        shape[-mom_ndim:] if integer, convert to tuple.
        """

        if moments is None:
            if shape is not None:
                if mom_ndim is None:
                    raise ValueError(
                        "must speficy either moments or shape and mom_ndim"
                    )
                moments = tuple(x - 1 for x in shape[-mom_ndim:])
            else:
                raise ValueError("must specify moments")

        if isinstance(moments, int):
            if mom_ndim is None:
                mom_ndim = 1
            moments = (moments,) * mom_ndim

        else:
            moments = tuple(moments)
            if mom_ndim is None:
                mom_ndim = len(moments)

        assert len(moments) == mom_ndim
        return moments

    @staticmethod
    def _datas_axis_to_first(
        datas, axis: int, mom_ndim: int, **kws
    ) -> Tuple[np.ndarray, int]:
        """Move axis to first first position."""
        # NOTE: removinvg this. should be handles elsewhere
        # datas = np.asarray(datas)
        # ndim = datas.ndim - mom_ndim
        # if axis < 0:
        #     axis += ndim
        # assert 0 <= axis < ndim
        axis = normalize_axis_index(axis, datas.ndim - mom_ndim)
        if axis != 0:
            datas = np.moveaxis(datas, axis, 0)
        return datas, axis

    def _wrap_axis(
        self, axis: int | None, default: int = 0, ndim: int | None = None, **kws
    ) -> int:
        """Wrap axis to positive value and check."""
        if axis is None:
            axis = default
        if ndim is None:
            ndim = self.val_ndim

        axis = cast(int, normalize_axis_index(axis, ndim))
        # if axis < 0:
        #     axis += ndim
        # assert 0 <= axis < ndim
        return axis

    @classmethod
    def _mom_ndim_from_mom(cls, mom: Union[Tuple[int], Tuple[int, int], int]) -> int:
        if isinstance(mom, int):
            return 1
        elif isinstance(mom, tuple):
            return len(mom)
        else:
            raise ValueError("mom must be int or tuple")

    @classmethod
    def _choose_mom_ndim(
        cls,
        mom: T_MOM | None,
        mom_ndim: int | None,
    ) -> int:
        if mom is not None:
            mom_ndim = cls._mom_ndim_from_mom(mom)

        if mom_ndim is None:
            raise ValueError("must specify mom_ndim or mom")

        return mom_ndim

    @classmethod
    @abstractmethod
    def from_data(
        cls: Type[T_CENTRALMOMENTS],
        data: Any,
        mom_ndim: int | None = None,
        mom: T_MOM | None = None,
        val_shape: Tuple[int, ...] | None = None,
        copy: bool = True,
        copy_kws: Mapping | None = None,
        verify: bool = True,
        check_shape: bool = True,
        dtype: DTypeLike | None = None,
    ) -> T_CENTRALMOMENTS:
        """Create new object from `data` array with additional checks.

        Parameters
        ----------
        data : np.np.ndarray
            shape should be val_shape + mom.
        mom_ndim : int, optional
            Number of moment dimensions.
            `mom_dim=1` for moments, `mom_dim=2` for comoments.
        mom : int or tuple, optional
            Moments. Defaults to data.shape[-mom_ndim:].
            Must specify either `mom_ndim` or `mom`.
            Verify data has correct shape.
        val_shape : tuple, optional
            shape of non-moment dimensions.  Used to check `data`
        copy : bool, default=True.
            If True, copy `data`.  If False, try to not copy.
        copy_kws : dict, optional
            parameters to np.np.ndarray.copy
        verify : bool, default=True
            If True, force data to have 'c' order
        check_shape : bool, default=True
            If True, check that `data` has correct shape (based on `mom` and `val_shape`)
        dtype : np.dtype, optional

        Returns
        -------
        out : CentralMoments instance
        """

    @classmethod
    @abstractmethod
    def from_datas(
        cls: Type[T_CENTRALMOMENTS],
        datas: Any,
        mom_ndim: int | None = None,
        axis: int | None = 0,
        mom: T_MOM | None = None,
        val_shape: Tuple[int, ...] | None = None,
        dtype: DTypeLike | None = None,
        verify: bool = True,
        check_shape: bool = True,
        **kws,
    ) -> T_CENTRALMOMENTS:
        """Create object from multiple data arrays.

        Parameters
        ----------
        datas : np.np.ndarray
            Array of multiple Moment arrays.
            datas[..., i, ...] is the ith data array, where i is
            in position `axis`.

        See Also
        --------
        CentralMoments.from_data
        """

    @classmethod
    @abstractmethod
    def from_vals(
        cls: Type[T_CENTRALMOMENTS],
        x,
        w=None,
        axis: int | None = 0,
        mom: T_MOM = 2,
        val_shape: Tuple[int, ...] | None = None,
        dtype: DTypeLike | None = None,
        broadcast: bool = False,
        **kws,
    ) -> T_CENTRALMOMENTS:
        """Create from observations/values.

        Parameters
        ----------
        x : array-like or tuple of array-like
            For moments, pass single array-like objects.
            For comoments, pass tuple of array-like objects.
        w : array-like, optional
            Optional weights.
        axis : int, default=0
            axis to reduce along.
        mom : int or tuple of ints
            For moments, pass an int.  For comoments, pass a tuple of ints.
        val_shape : tuple, optional
            shape array of values part of resulting object
        broadcast : bool, default=False
            If True, and doing comoments, broadcast x[1] to x[0]
        kws : dict
            optional arguments passed to cls.zeros

        Returns
        -------
        out : CentralMoments object
        """

    @classmethod
    def from_resample_vals(
        cls: Type[T_CENTRALMOMENTS],
        x,
        freq: np.ndarray | None = None,
        indices: np.ndarray | None = None,
        nrep: int | None = None,
        w: np.ndarray | None = None,
        axis: int = 0,
        mom: T_MOM = 2,
        dtype: DTypeLike | None = None,
        broadcast: bool = False,
        parallel: bool = True,
        resample_kws: Mapping | None = None,
        **kws,
    ) -> T_CENTRALMOMENTS:
        """Create from resample observations/values.

        This effectively resamples `x`.

        Parameters
        ----------
        x : array or tuple of arrays
            See CentralMoments.from_vals
        freq : array, optional
            Array of shape (nrep, size), where nrep is the number of
            replicates, and size is `x.shape(axis)`.
            `freq` is the weight that each sample contributes to the resampled values.
            See resample.randsamp_freq
        indices : array, optional
            Array of shape (nrep, size).  If passed, create `freq` from indices.
            See randsamp_freq.
        nrep : int, optional
            Number of replicates.  Create `freq` with this many replicates.
            See randsamp_freq
        w : array, optional.
            Optional weights associated with `x`.
        axis : int, default=0.
            Dimension to reduce/sample along.
        dtype : np.dtype, optional
            dtype of created output
        broadcast : bool, default=False
            If True, and calculating comoments, broadcast x[1] to x[0].shape
        parallel : bool, default=True
            If True, perform resampling in parallel.
        resample_kws : dict
            Extra arguments to resample.resample_vals
        kws : dict
            Extra arguments to CentralMoments.from_data

        Returns
        -------
        out : CentralMoments instance
        """

    @classmethod
    @abstractmethod
    def from_raw(
        cls: Type[T_CENTRALMOMENTS],
        raw,
        mom_ndim: int | None = None,
        mom: T_MOM | None = None,
        val_shape: Tuple[int, ...] | None = None,
        dtype: DTypeLike | None = None,
        convert_kws: Mapping | None = None,
        **kws,
    ) -> T_CENTRALMOMENTS:
        """Create object from raw.

        raw[..., i, j] = <x**i y**j>.
        raw[..., 0, 0] = {weight}


        Parameters
        ----------
        raw : np.np.ndarray
            Raw moment array.
        mom_ndim : int, optional
            Number of moment dimensions.
        mom : int or tuple, optional
            number of moments.
            Must specify `mom_ndim` or `mom`.
        val_shape : tuple, optional
            shape of non-moment dimensions.
        dtype : np.dtype
            dtype of output
        convert_kws : dict
            arguments to central to raw converter
        kws : dict
            Extra arguments to cls.from_data

        Returns
        -------
        out : instance of cls

        See Also
        --------
        convert.to_central_moments
        convert.to_central_comoments
        """

    @classmethod
    @abstractmethod
    def from_raws(
        cls: Type[T_CENTRALMOMENTS],
        raws,
        mom_ndim: int | None = None,
        mom: T_MOM | None = None,
        axis: int = 0,
        val_shape: Tuple[int, ...] | None = None,
        dtype: DTypeLike | None = None,
        convert_kws: Mapping | None = None,
        **kws,
    ) -> T_CENTRALMOMENTS:
        """Create object from multipel `raw` moment arrays.

        Parameters
        ----------
        raws : array
            raws[...,i,...] is the ith sample of a `raw` array,
            Note that raw[...,i,j] = <x0**i, x1**j>
        where `i` is in position `axis`
        axis : int, default=0

        See Also
        --------
        CentralMoments.from_raw : called by from_raws
        CentralMoments.from_datas : similar constructor for central moments
        """

    ###########################################################################
    # SECTION: Manipulation
    ###########################################################################
    @property
    def _is_vector(self) -> bool:
        return self.val_ndim > 0

    def _raise_if_scalar(self, message: str | None = None) -> None:
        if not self._is_vector:
            if message is None:
                message = "not implemented for scalar"
            raise ValueError(message)

    # Universal reducers
    def resample_and_reduce(
        self: T_CENTRALMOMENTS,
        freq: np.ndarray | None = None,
        indices: np.ndarray | None = None,
        nrep: None = None,
        axis: int | None = None,
        parallel: bool = True,
        resample_kws: Mapping | None = None,
        full_output: bool = False,
        **kws,
    ) -> T_CENTRALMOMENTS | Tuple[T_CENTRALMOMENTS, np.ndarray]:
        """Bootstrap resample and reduce.

        Parameter
        ----------
        freq : array-like, shape=(nrep, nrec), optional
            frequence table.  freq[i, j] is the weight of the jth record to the ith
            replicate indices : array-like, shape=(nrep, nrec), optional
            resampling array.  idx[i, j] is the record index of the original array to
            place in new sample[i, j]. if specified, create freq array from idx
        nrep : int, optional
            if specified, create idx array with this number of replicates
        axis : int, Default=0
            axis to resample and reduce along
        parallel : bool, default=True
            flags to `numba.njit`
        resample_kws : dict
            extra arguments to `cmomy.resample.resample_and_reduce`
        kws : dict
            extra key-word arguments to from_data method
        """
        self._raise_if_scalar()
        axis = self._wrap_axis(axis, **kws)
        if resample_kws is None:
            resample_kws = {}

        freq = randsamp_freq(
            nrep=nrep, indices=indices, freq=freq, size=self.val_shape[axis], check=True
        )
        data = resample_data(
            self.data, freq, mom=self.mom, axis=axis, parallel=parallel, **resample_kws
        )
        out = type(self).from_data(data, mom_ndim=self.mom_ndim, copy=False, **kws)

        if full_output:
            return out, freq
        else:
            return out

    def resample(
        self: T_CENTRALMOMENTS,
        indices: np.ndarray,
        axis: int = 0,
        first: bool = True,
        **kws,
    ) -> T_CENTRALMOMENTS:
        """Create a new object sampled from index.

        Parameters
        ----------
        indicies : array-like
            shape should be (nrep, nrec)
        axis : int, default=0
            axis to resample
        first : bool, default=True
            if True, and axis != 0, the move the axis to first position.
            This makes results similar to resample and reduce
            If `first` False, then resampled array can have odd shape

        Returns
        -------
        output : accumulator object
        """
        self._raise_if_scalar()
        axis = self._wrap_axis(axis, **kws)

        data = self.data
        if first and axis != 0:
            data = np.moveaxis(data, axis, 0)
            axis = 0

        out = np.take(data, indices, axis=axis)

        return type(self).from_data(
            data=out,
            mom_ndim=self.mom_ndim,
            mom=self.mom,
            copy=False,
            verify=True,
            **kws,
        )

    def reduce(
        self: T_CENTRALMOMENTS, axis: int | None = None, **kws
    ) -> T_CENTRALMOMENTS:
        """Create new object reducealong axis."""
        self._raise_if_scalar()
        axis = self._wrap_axis(axis, **kws)
        return type(self).from_datas(
            self.values, mom_ndim=self.mom_ndim, axis=axis, **kws
        )

    def block(
        self: T_CENTRALMOMENTS,
        block_size: int | None = None,
        axis: int | None = None,
        **kws,
    ) -> T_CENTRALMOMENTS:
        """Block average reduction.

        Parameters
        ----------
        block_size : int
            number of consecutive records to combine
        axis : int, default=0
            axis to reduce along
        kws : dict
            extral key word arguments to `from_datas` method
        """

        self._raise_if_scalar()

        axis = self._wrap_axis(axis, **kws)
        data = self.data

        # move axis to first
        if axis != 0:
            data = np.moveaxis(data, axis, 0)

        n = data.shape[0]

        if block_size is None:
            block_size = n
            nblock = 1

        else:
            nblock = n // block_size

        datas = data[: (nblock * block_size), ...].reshape(
            (nblock, block_size) + data.shape[1:]
        )
        return type(self).from_datas(datas=datas, mom_ndim=self.mom_ndim, axis=1, **kws)

    # --------------------------------------------------
    # mom_ndim == 1 specific
    # --------------------------------------------------

    # @staticmethod
    # def _raise_if_not_1d(mom_ndim: int) -> None:
    #     if mom_ndim != 1:
    #         raise NotImplementedError("only available for mom_ndim == 1")

    # special, 1d only methods
    # def push_stat(
    #     self: T_CENTRALMOMENTS,
    #     a: np.ndarray | float,
    #     v: np.ndarray | float = 0.0,
    #     w: np.ndarray | float | None = None,
    #     broadcast: bool = True,
    # ) -> T_CENTRALMOMENTS:
    #     """Push statisics onto self."""
    #     self._raise_if_not_1d(self.mom_ndim)

    #     ar, target = self._check_val(a, target="val")
    #     vr = self._check_var(v, broadcast=broadcast)
    #     wr = self._check_weight(w, target=target)
    #     self._push.stat(self._data_flat, wr, ar, vr)
    #     return self

    # def push_stats(
    #     self: T_CENTRALMOMENTS,
    #     a: np.ndarray,
    #     v: np.ndarray | float = 0.0,
    #     w: np.ndarray | float | None = None,
    #     axis: int = 0,
    #     broadcast: bool = True,
    # ) -> T_CENTRALMOMENTS:
    #     """Push multiple statistics onto self."""
    #     self._raise_if_not_1d(self.mom_ndim)

    #     ar, target = self._check_vals(a, target="vals", axis=axis)
    #     vr = self._check_vars(v, target=target, axis=axis, broadcast=broadcast)
    #     wr = self._check_weights(w, target=target, axis=axis)
    #     self._push.stats(self._data_flat, wr, ar, vr)
    #     return self

    # @classmethod
    # def from_stat(
    #     cls: Type[T_CENTRALMOMENTS],
    #     a: ArrayLike | float,
    #     v: np.ndarray | float = 0.0,
    #     w: np.ndarray | float | None = None,
    #     mom: T_MOM = 2,
    #     val_shape: Tuple[int, ...] | None = None,
    #     dtype: DTypeLike | None = None,
    #     order: ASARRAY_ORDER | None = None,
    #     **kws,
    # ) -> T_CENTRALMOMENTS:
    #     """Create object from single weight, average, variance/covariance."""
    #     mom_ndim = cls._mom_ndim_from_mom(mom)
    #     cls._raise_if_not_1d(mom_ndim)

    #     a = np.asarray(a, dtype=dtype, order=order)

    #     if val_shape is None and isinstance(a, np.ndarray):
    #         val_shape = a.shape
    #     if dtype is None:
    #         dtype = a.dtype

    #     return cls.zeros(val_shape=val_shape, mom=mom, dtype=dtype, **kws).push_stat(
    #         w=w, a=a, v=v
    #     )

    # @classmethod
    # def from_stats(
    #     cls: Type[T_CENTRALMOMENTS],
    #     a: np.ndarray,
    #     v: np.ndarray,
    #     w: np.ndarray | float | None = None,
    #     axis: int = 0,
    #     mom: T_MOM = 2,
    #     val_shape: Tuple[int, ...] = None,
    #     dtype: DTypeLike | None = None,
    #     order: ASARRAY_ORDER | None = None,
    #     **kws,
    # ) -> T_CENTRALMOMENTS:
    #     """Create object from several statistics.

    #     Weights, averages, variances/covarainces along
    #     axis.
    #     """

    #     mom_ndim = cls._mom_ndim_from_mom(mom)
    #     cls._raise_if_not_1d(mom_ndim)

    #     a = np.asarray(a, dtype=dtype, order=order)

    #     # get val_shape
    #     if val_shape is None:
    #         val_shape = _shape_reduce(a.shape, axis)
    #     return cls.zeros(val_shape=val_shape, dtype=dtype, mom=mom, **kws).push_stats(
    #         a=a, v=v, w=w, axis=axis
    #     )
