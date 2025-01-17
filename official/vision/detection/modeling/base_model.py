# Copyright 2019 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Base Model definition."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function


import abc
import functools
import re
import six
from absl import logging

import tensorflow.compat.v2 as tf
from official.vision.detection.modeling import checkpoint_utils
from official.vision.detection.modeling import learning_rates


class OptimizerFactory(object):
  """Class to generate optimizer function."""

  def __init__(self, params):
    """Creates optimized based on the specified flags."""
    if params.type == 'momentum':
      self._optimizer = functools.partial(
          tf.keras.optimizers.SGD, momentum=0.9, nesterov=True)
    elif params.type == 'adam':
      self._optimizer = tf.keras.optimizers.Adam
    elif params.type == 'adadelta':
      self._optimizer = tf.keras.optimizers.Adadelta
    elif params.type == 'adagrad':
      self._optimizer = tf.keras.optimizers.Adagrad
    elif params.type == 'rmsprop':
      self._optimizer = functools.partial(
          tf.keras.optimizers.RMSProp, momentum=params.momentum)
    else:
      raise ValueError('Unsupported optimizer type %s.' % self._optimizer)

  def __call__(self, learning_rate):
    return self._optimizer(learning_rate=learning_rate)


def _make_filter_trainable_variables_fn(frozen_variable_prefix):
  """Creates a function for filtering trainable varialbes.
  """

  def _filter_trainable_variables(variables):
    """Filters trainable varialbes

    Args:
      variables: a list of tf.Variable to be filtered.

    Returns:
      filtered_variables: a list of tf.Variable filtered out the frozen ones.
    """
    # frozen_variable_prefix: a regex string specifing the prefix pattern of
    # the frozen variables' names.
    filtered_variables = [
        v for v in variables
        if not re.match(frozen_variable_prefix, v.name)
    ]
    return filtered_variables

  return _filter_trainable_variables


class Model(object):
  """Base class for model function."""

  __metaclass__ = abc.ABCMeta

  def __init__(self, params):
    self._use_bfloat16 = params.architecture.use_bfloat16

    # Optimization.
    self._optimizer_fn = OptimizerFactory(params.train.optimizer)
    self._learning_rate = learning_rates.learning_rate_generator(
        params.train.learning_rate)

    self._frozen_variable_prefix = params.train.frozen_variable_prefix

    # Checkpoint restoration.
    self._checkpoint = params.train.checkpoint.as_dict()

    # Summary.
    self._enable_summary = params.enable_summary
    self._model_dir = params.model_dir

  @abc.abstractmethod
  def build_outputs(self, inputs, mode):
    """Build the graph of the forward path."""
    pass

  @abc.abstractmethod
  def build_model(self, params, mode):
    """Build the model object."""
    pass

  @abc.abstractmethod
  def build_loss_fn(self):
    """Build the model object."""
    pass

  def post_processing(self, labels, outputs):
    """Post-processing function."""
    return labels, outputs

  def model_outputs(self, inputs, mode):
    """Build the model outputs."""
    return self.build_outputs(inputs, mode)

  def build_optimizer(self):
    """Returns train_op to optimize total loss."""
    # Sets up the optimizer.
    return self._optimizer_fn(self._learning_rate)

  def make_filter_trainable_variables_fn(self):
    """Creates a function for filtering trainable varialbes.
    """
    return _make_filter_trainable_variables_fn(self._frozen_variable_prefix)

  def weight_decay_loss(self, l2_weight_decay, keras_model):
    # TODO(yeqing): Correct the filter according to  cr/269707763.
    return l2_weight_decay * tf.add_n([
        tf.nn.l2_loss(v)
        for v in self._keras_model.trainable_variables
        if 'batch_normalization' not in v.name
    ])

  def make_restore_checkpoint_fn(self):
    """Returns scaffold function to restore parameters from v1 checkpoint."""
    if 'skip_checkpoint_variables' in self._checkpoint:
      skip_regex = self._checkpoint['skip_checkpoint_variables']
    else:
      skip_regex = None
    return checkpoint_utils.make_restore_checkpoint_fn(
        self._checkpoint['path'],
        prefix=self._checkpoint['prefix'],
        skip_regex=skip_regex)

  def eval_metrics(self):
    """Returns tuple of metric function and its inputs for evaluation."""
    raise NotImplementedError('Unimplemented eval_metrics')
