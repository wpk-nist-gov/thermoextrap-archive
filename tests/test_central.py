import cmomy.accumulator as accumulator
import cmomy.accumulator_central as central

import numpy as np
import pytest

# central moments single variable
def _get_cmom_single(w, x, moments, axis=0):
    wsum = w.sum(axis)
    wsum_inv = 1.0 / wsum

    # get moments
    xave = (w * x).sum(axis) * wsum_inv
    data = [wsum, xave]
    dx = x - xave

    for n in range(2, moments + 1):
        y = (w * dx ** n).sum(axis) * wsum_inv
        data.append(y)

    data = np.array(data)
    return data

def _get_data_single(nrec=100, weighted=False):
    x = np.random.rand(nrec)
    if weighted is None:
        w = None
    elif weighted:
        w = np.random.rand(nrec)
    else:
        w = np.ones_like(x)
    return w, x




@pytest.mark.parametrize("nrec", [100])
@pytest.mark.parametrize("moments", [5])
@pytest.mark.parametrize("weighted", [False, True])
def test_StatsAccum_vals(nrec, moments, weighted):
    # unweighted
    w, x = _get_data_single(nrec, weighted)
    dataA = _get_cmom_single(w, x, moments)

    data = central.central_moments(x, moments, weights=w, axis=0)
    np.testing.assert_allclose(dataA, data)


    # push
    s = central.StatsAccum(moments=moments)
    for ww, xx in zip(w, x):
        s.push_val(xx, ww)
    np.testing.assert_allclose(s.data, data)

    # push_vals
    s.zero()
    s.push_vals(x, w)
    np.testing.assert_allclose(s.data, data)

    # from vals
    s = central.StatsAccum.from_vals(x, w, moments=moments)
    np.testing.assert_allclose(s.data, data)


@pytest.mark.parametrize("nrec", [100])
@pytest.mark.parametrize("moments", [5])
@pytest.mark.parametrize("weighted", [False, True])
def test_StatsAccum_stats(nrec, moments, weighted):
    # unweighted
    w, x = _get_data_single(nrec, weighted)
    dataA = _get_cmom_single(w, x, moments)

    data = central.central_moments(x, moments, w)
    np.testing.assert_allclose(data, dataA)

    splits = [len(x) // 3, len(x) // 3 * 2]

    ws = np.split(w, splits)
    xs = np.split(x, splits)

    datas = []
    for ww, xx in zip(ws, xs):
        datas.append(_get_cmom_single(ww, xx, moments))

    datas = np.array(datas)

    # factory
    s = central.StatsAccum.from_datas(datas, moments=moments)
    np.testing.assert_allclose(s.data, data)

    # pushs
    s = central.StatsAccum(moments=moments)

    for d in datas:
        s.push_stat(a=d[1], v=d[2:], w=d[0])
    np.testing.assert_allclose(s.data, data)

    s.zero()
    s.push_stats(a=datas[:, 1], v=datas[:, 2:], w=datas[:, 0])
    np.testing.assert_allclose(s.data, data)

    s.zero()
    s.push_datas(datas)
    np.testing.assert_allclose(s.data, data)

    # addition
    S = [central.StatsAccum.from_data(d, moments=moments) for d in datas]
    out = S[0]
    for s in S[1:]:
        out = out + s
    np.testing.assert_allclose(out.data, data)

    out = sum(S, central.StatsAccum(moments=moments))
    np.testing.assert_allclose(out.data, data)

    out = central.StatsAccum(moments=moments)
    for s in S:
        out += s
    np.testing.assert_allclose(out.data, data)

    # subtraction
    out = S[0] + S[1] - S[0]
    np.testing.assert_allclose(out.data, datas[1])

    # iadd/isub
    out = central.StatsAccum(moments=moments)
    out += S[0]
    np.testing.assert_allclose(out.data, S[0].data)

    out += S[1]
    np.testing.assert_allclose(out.data, (S[0] + S[1]).data)

    out -= S[0]
    np.testing.assert_allclose(out.data, S[1].data)

    # mult
    out1 = S[0] * 2
    out2 = S[0] + S[0]
    np.testing.assert_allclose(out1.data, out2.data)

    # imul
    out = central.StatsAccum.from_vals(xs[0], ws[0], moments=moments)
    out *= 2
    np.testing.assert_allclose(out.data, (S[0] + S[0]).data)


# central moments single variable
def _get_cmom_vec(w, x, moments, axis=0):

    if w.ndim == 1 and w.ndim != x.ndim and len(w) == x.shape[axis]:
        shape = [1] * x.ndim
        shape[axis] = -1
        w = w.reshape(*shape)

    if w.shape != x.shape:
        w = np.broadcast_to(w, x.shape)

    wsum_keep = w.sum(axis, keepdims=True)
    wsum_keep_inv = 1.0 / wsum_keep

    wsum = w.sum(axis)
    wsum_inv = 1.0 / wsum

    # get moments
    xave = (w * x).sum(axis, keepdims=True) * wsum_keep_inv
    dx = x - xave

    xmean = (w * x).sum(axis) * wsum_inv
    weight = wsum
    data = [weight, xmean]

    for n in range(2, moments + 1):
        y = (w * dx ** n).sum(axis) * wsum_inv
        data.append(y)

    data = np.array(data)
    return data


def _get_data_vec(shape, weighted=False):
    x = np.random.rand(*shape)

    if weighted is None:
        w = None
    elif weighted:
        w = np.random.rand(*shape)
    else:
        w = np.ones(shape)
    return w, x



@pytest.mark.parametrize("dshape,axis", [
    ((100,1), 0),
    ((10, 10), 0),
    ((10,10), 1),
    ((20,)*3, 0), ((20,)*3, 1), ((20,)*3, 2)
])
@pytest.mark.parametrize("moments", [5])
@pytest.mark.parametrize("weighted", [False, True])
def test_StatsAccumVec_vals(dshape, axis, moments, weighted):
    # unweighted
    wt, x = _get_data_vec(dshape, weighted)

    # single weight
    slicer = [0] * wt.ndim
    slicer[axis] = slice(None)
    ws = wt[tuple(slicer)]

    # push
    shape = list(dshape)
    shape.pop(axis)
    shape = tuple(shape)


    for w in (wt, ws):
        dataA = _get_cmom_vec(w, x, moments, axis=axis)
        data = central.central_moments(x, moments, w, axis=axis)

        np.testing.assert_allclose(data, dataA)

        s = central.StatsAccumVec(shape=shape, moments=moments)
        # push_vals
        s.push_vals(x, w, axis=axis)
        np.testing.assert_allclose(s.data, data)

        # from vals
        s = central.StatsAccumVec.from_vals(x, w, moments=moments, axis=axis)
        np.testing.assert_allclose(s.data, data)


@pytest.mark.parametrize("dshape,axis", [
    ((100,1), 0),
    ((10, 10), 0),
    ((10,10), 1),
    ((20,)*3, 0), ((20,)*3, 1), ((20,)*3, 2)
])
@pytest.mark.parametrize("moments", [5])
@pytest.mark.parametrize("weighted", [False, True])
def test_StatsAccumVec_stats(dshape, axis, moments, weighted):
    # unweighted
    wt, x = _get_data_vec(dshape, weighted)

    # single weight
    slicer = [0] * wt.ndim
    slicer[axis] = slice(None)
    ws = wt[tuple(slicer)]

    # push
    shape = list(dshape)
    shape.pop(axis)
    shape = tuple(shape)

    n = x.shape[axis]
    splits = [n //3, n //3*2]
    xsplit = np.split(x, splits, axis)

    for w in (wt, ws):
        dataA = _get_cmom_vec(w, x, moments, axis=axis)
        data = central.central_moments(x, moments, w, axis=axis)

        np.testing.assert_allclose(data, dataA)


        if w.ndim == 1:
            wsplit = np.split(w, splits)
        else:
            wsplit = np.split(w, splits, axis=axis)

        datas = []
        for ww, xx in zip(wsplit, xsplit):
            datas.append(central.central_moments(xx, moments, ww, axis=axis))# _get_cmom_vec(ww, xx, moments, axis=axis))
        datas = np.array(datas)

 

        # factory
        s = central.StatsAccumVec.from_datas(datas, moments=moments, axis=0)
        np.testing.assert_allclose(s.data, data)


        # pushs
        s = central.StatsAccumVec(moments=moments, shape=shape)

        for d in datas:
            s.push_stat(a=d[1], v=d[2:], w=d[0])
        np.testing.assert_allclose(s.data, data)

        s.zero()
        s.push_stats(a=datas[:, 1, ...], v=datas[:, 2:, ...], w=datas[:, 0, ...])
        np.testing.assert_allclose(s.data, data)

        s.zero()
        s.push_datas(datas)
        np.testing.assert_allclose(s.data, data)


        # addition
        S = [central.StatsAccumVec.from_data(d, moments=moments) for d in datas]
        out = S[0]
        for s in S[1:]:
            out = out + s
        np.testing.assert_allclose(out.data, data)

        out = sum(S, central.StatsAccumVec(shape=shape, moments=moments))
        np.testing.assert_allclose(out.data, data)

        out = central.StatsAccumVec(shape=shape, moments=moments)
        for s in S:
            out += s
        np.testing.assert_allclose(out.data, data)

        # subtraction
        out = S[0] + S[1] - S[0]
        np.testing.assert_allclose(out.data, datas[1])

        # iadd/isub
        out = central.StatsAccumVec(shape=shape, moments=moments)
        out += S[0]
        np.testing.assert_allclose(out.data, S[0].data)

        out += S[1]
        np.testing.assert_allclose(out.data, (S[0] + S[1]).data)

        out -= S[0]
        np.testing.assert_allclose(out.data, S[1].data)

        # mult
        out1 = S[0] * 2
        out2 = S[0] + S[0]
        np.testing.assert_allclose(out1.data, out2.data)

        # imul
        out = S[0].copy()
        out *= 2
        np.testing.assert_allclose(out.data, (S[0] + S[0]).data)





