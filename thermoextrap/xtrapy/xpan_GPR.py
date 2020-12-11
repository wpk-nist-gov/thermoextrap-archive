"""
Routines GPR interpolation models
"""

from __future__ import absolute_import

import xarray as xr
import sympy as sp
import numpy as np
import tensorflow as tf
import gpflow
from gpflow.ci_utils import ci_niter

from .core import StateCollection


#First define classes needed for a GPR model
#A general derivative kernel based on a sympy expression
class DerivativeKernel(gpflow.kernels.Kernel):
    """
    Creates a kernel that can be differentiated based on a sympy expression for the kernel.
Given observations that are tagged with the order of the derivative, builds the appropriate 
kernel. Be warned that your kernel_expr will not be checked to make sure it is positive 
definite, stationary, etc.

There are rules for kernel_expr and kernel_params that guarantee consistency. First, the 
variable names supplied as keys to kernel_params should match the symbol names in 
kernel_expr. Symbol names for the inputs should be 'x1' and 'x2' (ignoring case). We could 
accept anything as long as 2 symbols are left over after those in kernel_params, but these 
two rules will guarantee that nothing breaks.

Currently, everything is only intended to work with 1D observables.

    Inputs:
           kernel_expr - sympy expression for the kernel that can be differentiated - must
                         have at least 2 symbols
                         (symbol names should be 'x1' and 'x2', case insensitive, if have
                          only 2)
           obs_dims - number of dimensions for observable input
                      (input should be twice this with obs_dims values then obs_dims
                       derivative labels each row)
           kernel_params - a dictionary of kernel parameters that can be optimized by
                           tensorflow
                           (key should be name, then references list with value then
                            another dict with kwargs for gpflow.Parameter, i.e.,
                            {'variance', [1.0, {'transform':gpflow.utilities.positive()}]}
                            so if you don't want to set any kwargs, just pass empty
                            dictionary
                           NOTE THAT THE KEYS MUST MATCH THE SYMBOL NAMES IN kernel_expr
                           OTHER THAN 'x1' and 'x2'
                           Default is empty dict, so will mine names from kernel_expr and
                           set all parameters to 1.0
    """

    def __init__(self, kernel_expr, obs_dims, kernel_params={}, active_dims=None, **kwargs):

        if active_dims is not None:
            print("active_dims set to: ", active_dims)
            print("This is not implemented in this kernel, so setting to 'None'")
            active_dims = None

        super().__init__(active_dims=active_dims, **kwargs)

        #Get the sympy expression for the kernel
        self.kernel_expr = kernel_expr
        #Now need to mine it a little bit to get the adjustable parameters and input variables
        expr_syms = tuple(kernel_expr.free_symbols)
        #Require that have two symbols called x1 and x2, with the rest being parameters
        self.x_syms = []
        self.param_syms = []
        for s in expr_syms:
            if (s.name.casefold() == 'x1' or s.name.casefold() == 'x2'):
                self.x_syms.append(s)
            else:
                self.param_syms.append(s)
        #Make sure to sort so clearly define x1 and x2
        list(self.x_syms).sort(key=lambda s: s.name)
        #If have no other symbols (i.e. parameters) there is nothing to optimize!
        if len(self.param_syms) == 0:
            raise ValueError('Provided kernel expression only takes inputs x1 and x2, '
                             +'no optimizable parameters!')
        #Make sure that parameters here match those in kernel_params, if it's provided
        if bool(kernel_params):
            if list([s.name for s in self.param_syms]).sort() != list(kernel_params.keys()).sort():
                raise ValueError('Symbol names in kernel_expr must match keys in '
                                 +'kernel_params!')
            #If they are the same, obtain parameter values from kernel_params dictionary
            #Need to set as gpflow Parameter objects so can optimize over them
            for key, val in kernel_params.items():
                setattr(self, key, gpflow.Parameter(val[0], **val[1]))

        #If kernel_params is not provided, set everything to 1.0 by default
        else:
            for s in self.param_syms:
                setattr(self, s.name, gpflow.Parameter(1.0))

        #Set number of observable dimensions
        self.obs_dims = obs_dims

    #Define ARD behavior (if ever want multiple dimensions with different lengthscales)
    @property
    def ard(self) -> bool:
        """
        Whether ARD behavior is active, following gpflow.kernels.Stationary
        """
        return self.lengthscales.shape.ndims > 0

    def K(self, X, X2=None):
        if X2 is None:
            X2 = X

        x1, d1 = self._split_x_into_locs_and_deriv_info(X)
        x2, d2 = self._split_x_into_locs_and_deriv_info(X2)

        #Output should be a tensor that is len(X) by len(X2) - at least in 1D, not
        #sure what to do otherwise
        #And must be traceable with tensorflow's autodifferentiation
        #(in the inherited kernel parameters)

        #Want full list of all combinations of derivative pairs
        #Definitely only works for 1D data because of way reshaping
        expand_d1 = np.reshape(np.tile(d1, (1, d2.shape[0])), (d1.shape[0]*d2.shape[0], -1))
        expand_d2 = np.tile(d2, (d1.shape[0], 1))
        deriv_pairs = np.hstack([expand_d1, expand_d2])

        #For convenience, do same with x, but no need to stack
        #Sort of same idea as creating a mesh grid
        expand_x1 = np.reshape(np.tile(x1, (1, x2.shape[0])), (x1.shape[0]*x2.shape[0], -1))
        expand_x2 = np.tile(x2, (x1.shape[0], 1))

        #Now need UNIQUE derivative pairs because will be faster to loop over
        unique_pairs = np.unique(deriv_pairs, axis=0)

        #Loop over unique pairs, tracking indices and kernel values for pairs
        k_list = []
        inds_list = []
        for pair in unique_pairs:
            #Get the right indices
            this_inds = np.where(np.all(deriv_pairs == pair, axis=1))[0]
            #Use sympy to obtain right derivative
            this_expr = sp.diff(self.kernel_expr,
                                self.x_syms[0], int(pair[0]),
                                self.x_syms[1], int(pair[1]))
            #Get lambdified function compatible with tensorflow
            this_func = sp.lambdify((self.x_syms[0], self.x_syms[1], *self.param_syms),
                                     this_expr,
                                     modules="tensorflow")
            #Plug in our values for the derivative kernel
            k_list.append(this_func(expand_x1[this_inds], expand_x2[this_inds],
                                    *[getattr(self, s.name) for s in self.param_syms]))
            #Also keep track of indices so can dynamically stitch back together
            inds_list.append(this_inds)

        #Stitch back together
        k_list = tf.dynamic_stitch(inds_list, k_list)

        #Reshape to the correct output - will only really work for 1D, I think
        k_mat = tf.reshape(k_list, (x1.shape[0], x2.shape[0]))
        return k_mat

    def K_diag(self, X):
        #Same as for K but don't need every combination, just every x with itself
        x1, d1 = self._split_x_into_locs_and_deriv_info(X)
        unique_d1 = np.unique(d1)
        k_list = []
        inds_list = []
        for d in unique_d1:
            this_inds = np.where(d1 == unique_d1)[0]
            this_expr = sp.diff(self.kernel_expr,
                                self.x_syms[0], int(d),
                                self.x_syms[1], int(d))
            this_func = sp.lambdify((self.x_syms[0], self.x_syms[1], *self.param_syms),
                                     this_expr,
                                     modules="tensorflow")
            k_list.append(this_func(x1[this_inds], x1[this_inds],
                                    *[getattr(self, s.name) for s in self.param_syms]))
            inds_list.append(this_inds)

        k_list = tf.dynamic_stitch(inds_list, k_list)
        k_diag = tf.reshape(k_list, (x1.shape[0],))
        return k_diag

    def _split_x_into_locs_and_deriv_info(self, x):
        """Splits input into actual observable input and derivative labels
        """
        locs = x[:, :self.obs_dims]
        grad_info = x[:, -self.obs_dims:]
        return locs, grad_info


#A custom GPFlow likelihood with heteroscedastic Gaussian noise
#Comes from GPFlow tutorial on this subject
class HeteroscedasticGaussian(gpflow.likelihoods.Likelihood):
    def __init__(self, **kwargs):
        # this likelihood expects a single latent function F, and two columns in
        # the data matrix Y:
        super().__init__(latent_dim=1, observation_dim=2, **kwargs)

    def _log_prob(self, F, Y):
        # log_prob is used by the quadrature fallback of variational_expectations
        # and predict_log_density.
        # Because variational_expectations is implemented analytically below, this is
        # not actually needed.
        Y, NoiseVar = Y[:, 0], Y[:, 1]
        return gpflow.logdensities.gaussian(Y, F, NoiseVar)

    def _variational_expectations(self, Fmu, Fvar, Y):
        Y, NoiseVar = Y[:, 0], Y[:, 1]
        Fmu, Fvar = Fmu[:, 0], Fvar[:, 0]
        return (
            -0.5 * np.log(2 * np.pi)
            - 0.5 * tf.math.log(NoiseVar)
            - 0.5 * (tf.math.square(Y - Fmu) + Fvar) / NoiseVar
        )

    # The following two methods are abstract in the base class.
    # They need to be implemented even if not used.

    def _predict_log_density(self, Fmu, Fvar, Y):
        raise NotImplementedError

    def _predict_mean_and_var(self, Fmu, Fvar):
        raise NotImplementedError


#Now can construct a model class inheriting from StateCollection
class GPRModel(StateCollection):

    def _collect_data(self, order=None, order_name="order", n_resample=100):
        if order is None:
            order = self.order
        x_data = np.reshape([m.alpha0 for m in self.states], (-1, 1))
        #For each alpha value, stack order+1 times and signify derivative order
        x_data = np.reshape(np.tile(x_data, (1, order+1)), (-1, 1))
        x_data = np.concatenate([x_data,
                                 np.tile(np.arange(order+1)[:, None], (len(self.states), 1))],
                                axis=1)
        #Collect all derivatives and uncertainties at each alpha and reshape
        y_data_xr = []
        y_data_err_xr = []
        for m in self.states:
          #Set norm to False so does not divide by factorial of each derivative order
          y_data_xr.append(m.xcoefs(order=order, order_name=order_name, norm=False))
          #Obtain variances by bootstrap resampling of original data and compute for each
          this_boot = m.resample(n_resample).xcoefs(order=order, order_name=order_name,
                                                    norm=False)
          y_data_err_xr.append(this_boot.std('rep'))
        y_data_xr = xr.concat(y_data_xr, dim='state')
        y_data_err_xr = xr.concat(y_data_err_xr, dim='state')
        #Need to flatten order and state dimensions together
        #ORDER MATTERS - we want state first to be consistent with x_data
        y_data_xr = y_data_xr.stack(flat_state=('state', 'order'))
        y_data_err_xr = y_data_err_xr.stack(flat_state=('state', 'order'))
        #And create numpy array
        y_data = np.concatenate([y_data_xr.transpose('flat_state', 'val').values,
                                 y_data_err_xr.transpose('flat_state', 'val').values], axis=1)
        return x_data, y_data

    #Define function to train the Gaussian process
    #Hopefully, won't need to re-train many times with changing data
    #However, if do need to and want to keep same model, this allows for that
    def _train_GP(self, x_input, y_input, opt_steps=100, fresh_train=False):

        #Want option to continue training with same model, so adding in
        #So default behavior is fresh_train=False, so continues training if model exists
        #Might use to add extra training or if add more data
        #If set fresh_train to True, will get new model - need if change order
        if self.gp is None or fresh_train:
            self.gp = gpflow.models.VGP((x_input, y_input),
                                        kernel=self.kern,
                                        likelihood=self.het_gauss,
                                        num_latent_gps=1)

        #Make some parameters fixed
        gpflow.set_trainable(self.gp.q_mu, False)
        gpflow.set_trainable(self.gp.q_sqrt, False)

        #Run optimization
        natgrad = gpflow.optimizers.NaturalGradient(gamma=1.0)
        adam = tf.optimizers.Adam()
        for _ in range(ci_niter(opt_steps)):
            natgrad.minimize(self.gp.training_loss, [(self.gp.q_mu, self.gp.q_sqrt)])
            adam.minimize(self.gp.training_loss, self.gp.trainable_variables)


    def __init__(self, states, kernel_expr, kernel_params={}, **kwargs):

        super().__init__(states, **kwargs)

        self.kern = DerivativeKernel(kernel_expr,
                                     self.states[0].data.xv.shape[1], #Better way, Bill?
                                     kernel_params=kernel_params)
        self.het_gauss = HeteroscedasticGaussian()

        #Initially train GPR model
        self.gp = None
        x_in, y_in = self._collect_data()
        self._train_GP(x_in, y_in)

    def predict(self, alpha, order=None, order_name='order', alpha_name=None):

        if order is None:
            order = self.order
        elif order != self.order:
            #In this case, must retrain GP at different order
            #So try not to do this if possible
            x_in, y_in = self._collect_data(order=order, order_name=order_name)
            self._train_GP(x_in, y_in, fresh_train=True)

        x_pred = np.hstack([np.reshape(alpha, (-1, 1)), np.zeros((alpha.shape[0], 1))])
        out = self.gp.predict_f(x_pred)

        #Make it an xarray for consistency
        #Output from predict_f is mean and variance, so split up
        if alpha_name is None:
          alpha_name = self.alpha_name
        mean_out = xr.DataArray(out[0],
                                dims=(alpha_name, 'val'), coords={alpha_name:alpha})
        std_out = xr.DataArray(np.sqrt(out[1]),
                               dims=(alpha_name, 'val'), coords={alpha_name:alpha})
        return mean_out, std_out


def factory_rbf_gprmodel(states, **kws):
    """
    factory function to create GPR model for beta expanssion

    Parameters
    ----------
    states : StateCollection of ExtrapModel objects
    **kws : additional keyword arguments to pass to the model

    Returns
    -------
    gprmodel : GPRModel object
    """

    #Define RBF kernel expression and parameters
    var = sp.symbols('var')
    l = sp.symbols('l')
    x1 = sp.symbols('x1')
    x2 = sp.symbols('x2')
    rbf_kern_expr = var*sp.exp(-0.5*(x1/l - x2/l)**2)

    rbf_params = {'var':[1.0, {'transform':gpflow.utilities.positive()}],
                  'l':[1.0, {'transform':gpflow.utilities.positive()}]}

    return GPRModel(states, rbf_kern_expr, rbf_params, **kws)


