#!/usr/bin/env python
"""
Produce Python code for simulating a PySB model without requiring PySB itself
(note that NumPy and SciPy are still required). This offers a way of
distributing a model to those who do not have PySB. Can be used as a
command-line script or from within the Python shell.

Usage as a command-line script
==============================

As a command-line script, run as follows::

    export_potterswheel.py model_name.py > model_standalone.py

where ``model_name.py`` contains a PySB model definition (i.e., contains an
instance of ``pysb.core.Model`` instantiated as a global variable). The text of
the generated Python code will be printed to standard out, allowing it to be
redirected to another file, as shown in this example.

Usage in the Python shell
=========================

To use in a Python shell, import a model::

    from pysb.examples.robertson import model

and import this module::

    from pysb.tools import export_python

then call the function ``run``, passing the model instance::

    python_output = export_python.run(model)

then write the output to a file::

    f = open('robertson_standalone.py', 'w')
    f.write(python_output)
    f.close()

Structure of the standalone Python code
=======================================

The standalone Python code defines a class, ``Model``, with a method
``simulate`` that can be used to simulate the model.

As shown in the code for the Robertson model below, the ``Model`` class defines
the fields ``parameters``, ``observables``, and ``initial_conditions`` as lists
of ``collections.namedtuple`` objects that allow access to the features of the
model.

The ``simulate`` method has the following signature::

    def simulate(self, tspan, param_values=None, view=False):

with arguments as follows:

* ``tspan`` specifies the array of timepoints
* ``param_values`` is an optional vector of parameter values that can be used
  to override the nominal values defined in the PySB model
* ``view`` is an optional boolean argument that specifies if the simulation
  output arrays are returned as copies (views) of the original. If True,
  returns copies of the arrays, allowing changes to be made to values in the
  arrays without affecting the originals.

``simulate`` returns a tuple of two arrays. The first array is a matrix
with timecourses for each species in the model as the columns. The
second array is a numpy record array for the model's observables, which can
be indexed by name.

Output for the Robertson example model
======================================

Example code generated for the Robertson model, ``pysb.examples.robertson``:

.. literalinclude:: ../examples/robertson_standalone.py

Using the standalone Python model
=================================

An example usage pattern for the standalone Robertson model, once generated::

    # Import the standalone model file
    import robertson_standalone
    import numpy
    from matplotlib import pyplot as plt

    # Instantiate the model object (the constructor takes no arguments)
    model = robertson_standalone.Model()

    # Simulate the model
    tspan = numpy.linspace(0, 100)
    (species_output, observables_output) = model.simulate(tspan)

    # Plot the results
    plt.figure()
    plt.plot(tspan, observables_output['A_total'])
    plt.show()
"""

import pysb
import pysb.bng
import sympy
import re
import sys
import os
import textwrap
from StringIO import StringIO


def pad(text, depth=0):
    "Dedent multi-line string and pad with spaces."
    text = textwrap.dedent(text)
    text = re.sub(r'^(?m)', ' ' * depth, text)
    text += '\n'
    return text

def run(model, docstring=None):
    """Export Python code for simulation of a model without PySB.

    Parameters
    ----------
    model : pysb.core.Model
        The model to export as a standalone Python program.
    docstring : string
        The header docstring to include at the top of the generated Python
        code.

    Returns
    -------
    string
        String containing the standalone Python code.
    """

    output = StringIO()
    pysb.bng.generate_equations(model)

    # Note: This has a lot of duplication from pysb.integrate.
    # Can that be helped?

    code_eqs = '\n'.join(['ydot[%d] = %s;' % (i, sympy.ccode(model.odes[i]))
                          for i in range(len(model.odes))])
    code_eqs = re.sub(r's(\d+)',
                      lambda m: 'y[%s]' % (int(m.group(1))), code_eqs)
    for i, p in enumerate(model.parameters):
        code_eqs = re.sub(r'\b(%s)\b' % p.name, 'p[%d]' % i, code_eqs)

    output.write('"""')
    output.write(docstring)
    output.write('"""\n\n')
    output.write("# exported from PySB model '%s'\n" % model.name)
    output.write(pad(r"""
        import numpy
        import scipy.weave, scipy.integrate
        import collections
        import itertools
        import distutils.errors
        """))
    output.write(pad(r"""
        _use_inline = False
        # try to inline a C statement to see if inline is functional
        try:
            scipy.weave.inline('int i;', force=1)
            _use_inline = True
        except distutils.errors.CompileError:
            pass

        Parameter = collections.namedtuple('Parameter', 'name value')
        Observable = collections.namedtuple('Observable', 'name species coefficients')
        Initial = collections.namedtuple('Initial', 'param_index species_index')
        """))
    output.write("\n")

    output.write("class Model(object):\n")
    init_data = {
        'num_species': len(model.species),
        'num_params': len(model.parameters),
        'num_observables': len(model.observables),
        'num_ics': len(model.initial_conditions),
        }
    output.write(pad(r"""
        def __init__(self):
            self.y = None
            self.yobs = None
            self.integrator = scipy.integrate.ode(self.ode_rhs)
            self.integrator.set_integrator('vode', method='bdf',
                                           with_jacobian=True)
            self.y0 = numpy.empty(%(num_species)d)
            self.ydot = numpy.empty(%(num_species)d)
            self.sim_param_values = numpy.empty(%(num_params)d)
            self.parameters = [None] * %(num_params)d
            self.observables = [None] * %(num_observables)d
            self.initial_conditions = [None] * %(num_ics)d
        """, 4) % init_data)
    for i, p in enumerate(model.parameters):
        p_data = (i, repr(p.name), p.value)
        output.write(" " * 8)
        output.write("self.parameters[%d] = Parameter(%s, %g)\n" % p_data)
    output.write("\n")
    for i, obs in enumerate(model.observables):
        obs_data = (i, repr(obs.name), repr(obs.species),
                    repr(obs.coefficients))
        output.write(" " * 8)
        output.write("self.observables[%d] = Observable(%s, %s, %s)\n" %
                     obs_data)
    output.write("\n")
    for i, (cp, param) in enumerate(model.initial_conditions):
        ic_data = (i, model.parameters.index(param),
                   model.get_species_index(cp))
        output.write(" " * 8)
        output.write("self.initial_conditions[%d] = Initial(%d, %d)\n" %
                     ic_data)
    output.write("\n")

    output.write("    if _use_inline:\n")
    output.write(pad(r"""
        def ode_rhs(self, t, y, p):
            ydot = self.ydot
            scipy.weave.inline(r'''%s''', ['ydot', 't', 'y', 'p'])
            return ydot
        """, 8) % (pad('\n' + code_eqs, 16) + ' ' * 16))
    output.write("    else:\n")
    output.write(pad(r"""
        def ode_rhs(self, t, y, p):
            ydot = self.ydot
            %s
            return ydot
        """, 8) % pad('\n' + code_eqs, 12).replace(';','').strip())

    # note the simulate method is fixed, i.e. it doesn't require any templating
    output.write(pad(r"""
        def simulate(self, tspan, param_values=None, view=False):
            if param_values is not None:
                # accept vector of parameter values as an argument
                if len(param_values) != len(self.parameters):
                    raise Exception("param_values must have length %d" %
                                    len(self.parameters))
                self.sim_param_values[:] = param_values
            else:
                # create parameter vector from the values in the model
                self.sim_param_values[:] = [p.value for p in self.parameters]
            self.y0.fill(0)
            for ic in self.initial_conditions:
                self.y0[ic.species_index] = self.sim_param_values[ic.param_index]
            if self.y is None or len(tspan) != len(self.y):
                self.y = numpy.empty((len(tspan), len(self.y0)))
                if len(self.observables):
                    self.yobs = numpy.ndarray(len(tspan),
                                    zip((obs.name for obs in self.observables),
                                        itertools.repeat(float)))
                else:
                    self.yobs = numpy.ndarray((len(tspan), 0))
                self.yobs_view = self.yobs.view(float).reshape(len(self.yobs),
                                                               -1)
            # perform the actual integration
            self.integrator.set_initial_value(self.y0, tspan[0])
            self.integrator.set_f_params(self.sim_param_values)
            self.y[0] = self.y0
            t = 1
            while self.integrator.successful() and self.integrator.t < tspan[-1]:
                self.y[t] = self.integrator.integrate(tspan[t])
                t += 1
            for i, obs in enumerate(self.observables):
                self.yobs_view[:, i] = \
                    (self.y[:, obs.species] * obs.coefficients).sum(1)
            if view:
                y_out = self.y.view()
                yobs_out = self.yobs.view()
                for a in y_out, yobs_out:
                    a.flags.writeable = False
            else:
                y_out = self.y.copy()
                yobs_out = self.yobs.copy()
            return (y_out, yobs_out)
        """, 4))

    return output.getvalue()


if __name__ == '__main__':
    # sanity checks on filename
    if len(sys.argv) <= 1:
        raise Exception("You must specify the filename of a model script")
    model_filename = sys.argv[1]
    if not os.path.exists(model_filename):
        raise Exception("File '%s' doesn't exist" % model_filename)
    if not re.search(r'\.py$', model_filename):
        raise Exception("File '%s' is not a .py file" % model_filename)
    sys.path.insert(0, os.path.dirname(model_filename))
    model_name = re.sub(r'\.py$', '', os.path.basename(model_filename))
    # import it
    try:
        # FIXME if the model has the same name as some other "real" module
        # which we use, there will be trouble
        # (use the imp package and import as some safe name?)
        model_module = __import__(model_name)
    except StandardError as e:
        print "Error in model script:\n"
        raise
    # grab the 'model' variable from the module
    try:
        model = model_module.__dict__['model']
    except KeyError:
        raise Exception("File '%s' isn't a model file" % model_filename)
    print run(model, model_module.__doc__)
