# Copyright 2017 Giorgia Fenoglio, Mattia Cerrato
#
# This file is part of NNsTaxonomicResponding.
#
# NNsTaxonomicResponding is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# NNsTaxonomicResponding is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with NNsTaxonomicResponding.  If not, see <http://www.gnu.org/licenses/>.

import tensorflow as tf
import numpy as np
import math
import os
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams.update({'font.size': 8})
import matplotlib.pyplot as plt
from utils.constants import Constants
from matplotlib import colors
from scipy.stats import f as fisher_f
from scipy.stats import norm
from profilehooks import profile



class SOM(object):
    """
    2-D Self-Organizing Map with Gaussian Neighbourhood function
    and linearly decreasing learning rate.
    """

    #To check if the SOM has been trained
    _trained = False


    def __init__(self, m, n, dim, n_iterations=50, alpha=None, sigma=None,
                 tau=0.5, threshold=0.6, batch_size=500, num_classes=10,
                 checkpoint_dir = None, data='audio'):
        """
        Initializes all necessary components of the TensorFlow
        Graph.

        m X n are the dimensions of the SOM. 'n_iterations' should
        should be an integer denoting the number of iterations undergone
        while training.
        'dim' is the dimensionality of the training inputs.
        'alpha' is a number denoting the initial time(iteration no)-based
        learning rate. Default value is 0.3
        'sigma' is the the initial neighbourhood value, denoting
        the radius of influence of the BMU while training. By default, its
        taken to be half of max(m, n).
        """

        #Assign required variables first
        self._m = m
        self._n = n
        if alpha is None:
            self.alpha = 0.3
        else:
            self.alpha = float(alpha)

        if sigma is None:
            self.sigma = max(m, n) / 2.0
        else:
            self.sigma = float(sigma)

        self.tau = tau
        self.threshold = threshold

        self.batch_size = batch_size

        self._n_iterations = abs(int(n_iterations))

        self.logs_path = Constants.DATA_FOLDER + '/tblogs/' + self.get_experiment_name(data)

        if not os.path.exists(self.logs_path):
            os.makedirs(self.logs_path)

        if checkpoint_dir is None:
          self.checkpoint_dir = Constants.DATA_FOLDER + '/saved_models/'
        else:
          self.checkpoint_dir = checkpoint_dir

        ##INITIALIZE GRAPH
        self._graph = tf.Graph()

        ##POPULATE GRAPH WITH NECESSARY COMPONENTS
        with self._graph.as_default():

            ##VARIABLES AND CONSTANT OPS FOR DATA STORAGE

            #Randomly initialized weightage vectors for all neurons,
            #stored together as a matrix Variable of size [m*n, dim]
            self._weightage_vects = tf.Variable(tf.random_normal(
                [m*n, dim], mean=0, stddev=1))

            #Matrix of size [m*n, 2] for SOM grid locations
            #of neurons
            self._location_vects = tf.constant(np.array(
                list(self._neuron_locations(m, n))))

            ##PLACEHOLDERS FOR TRAINING INPUTS
            #We need to assign them as attributes to self, since they
            #will be fed in during training

            #The training vectors
            self._vect_input = tf.placeholder("float", [None, dim])
            #Class vectors, useful for computing class compactness as we train
            self._class_input = tf.placeholder("int32", [None])
            #Test vectors and test classes
            self._vect_test = tf.placeholder("float", [None, dim])
            self._class_test = tf.placeholder("int32", [None])
            #Iteration number
            self._iter_input = tf.placeholder("float")
            #Summaries placeholder
            self._train_compactness = tf.placeholder("float")
            self._test_compactness = tf.placeholder("float")
            self._train_population_convergence = tf.placeholder("float")
            self._test_population_convergence = tf.placeholder("float")
            self._train_mean_convergence = tf.placeholder("float")
            self._test_mean_convergence = tf.placeholder("float")
            self._train_var_convergence = tf.placeholder("float")
            self._test_var_convergence = tf.placeholder("float")
            self._avg_delta = tf.placeholder("float")

            ##SUMMARIES
            train_mean, train_std = tf.nn.moments(self._train_compactness, axes=[0])
            test_mean, test_std = tf.nn.moments(self._test_compactness, axes=[0])
            tf.summary.scalar("Train Mean Compactness", train_mean)
            tf.summary.scalar("Test Mean Compactness", test_mean)
            tf.summary.scalar("Train Compactness Variance", train_std)
            tf.summary.scalar("Test Compactness Variance", test_std)
            tf.summary.scalar("Train Population Convergence", self._train_population_convergence)
            tf.summary.scalar("Test Population Convergence", self._test_population_convergence)
            tf.summary.scalar("Train Mean Convergence", self._train_mean_convergence)
            tf.summary.scalar("Test Mean Convergence", self._test_mean_convergence)
            tf.summary.scalar("Train Var Convergence", self._train_var_convergence)
            tf.summary.scalar("Test Var Convergence", self._test_var_convergence)
            tf.summary.scalar("Average Delta", self._avg_delta)

            # will be set when computing the class compactness for the first time
            self.train_inter_class_distance = None
            self.test_inter_class_distance = None

            self.summaries = tf.summary.merge_all()

            ##CONSTRUCT TRAINING OP PIECE BY PIECE
            #Only the final, 'root' training op needs to be assigned as
            #an attribute to self, since all the rest will be executed
            #automatically during training

            bmu_indexes = self._get_bmu(self._vect_input)

            #This will extract the location of the BMU based on the BMU's
            #index. This has dimensionality [batch_size, 2] where 2 is (i, j),
            #the location of the BMU in the map
            bmu_loc = tf.gather(self._location_vects, bmu_indexes)

            #To compute the alpha and sigma values based on iteration
            #number
            learning_rate = 1.0 - tf.div(self._iter_input, tf.cast(self._n_iterations, "float"))
            _alpha_op = self.alpha * learning_rate
            _sigma_op = self.sigma * learning_rate

            #Construct the op that will generate a vector with learning
            #rates for all neurons, based on iteration number and location
            #wrt BMU.

            #Tensor of shape [batch_size, num_neurons] containing the distances
            #between the BMU and all other neurons, for each batch
            bmu_distance_squares = self._get_bmu_distances(bmu_loc)

            neighbourhood_func = tf.exp(tf.negative(tf.div(tf.cast(
                bmu_distance_squares, "float32"), tf.pow(_sigma_op, 2))))
            learning_rate_op = _alpha_op * neighbourhood_func

            #Finally, the op that will use learning_rate_op to update
            #the weightage vectors of all neurons based on a particular
            #input
            learning_rate_matrix = _alpha_op * neighbourhood_func

            self.weightage_delta = self._get_weight_delta(learning_rate_matrix)

            new_weightages_op = tf.add(self._weightage_vects,
                                       self.weightage_delta)
            self._training_op = tf.assign(self._weightage_vects,
                                          new_weightages_op)

            ##INITIALIZE SESSION
            #uncomment this to run on cpu
            config = tf.ConfigProto(
                device_count = {'GPU': 0}
            )
            self._sess = tf.Session(config=config)


            ##INITIALIZE VARIABLES
            init_op = tf.global_variables_initializer()
            self._sess.run(init_op)

    def _get_weight_delta(self, learning_rate_matrix):
        """
        """
        diff_matrix = tf.cast(tf.expand_dims(self._vect_input, 1) - self._weightage_vects, "float32")
        mul = tf.expand_dims(learning_rate_matrix, 2) * diff_matrix
        delta = tf.reduce_mean(mul, 0)
        return delta

    def _get_bmu_distances(self, bmu_loc):
        """
        """
        squared_distances = tf.reduce_sum((self._location_vects - tf.expand_dims(bmu_loc, 1)) ** 2, 2)
        return squared_distances

    def _get_bmu(self, vects):
        """
        Returns the BMU for each example in vect. The return value's dimensionality
        is therefore vect.shape[0]
        """
        squared_differences = (self._weightage_vects - tf.expand_dims(vects, 1)) ** 2
        squared_distances = tf.reduce_sum(squared_differences, 2)
        bmu_index = tf.argmin(squared_distances, 1)
        return bmu_index

    def _neuron_locations(self, m, n):
        """
        Yields one by one the 2-D locations of the individual neurons
        in the SOM.
        """
        #Nested iterations over both dimensions
        #to generate all 2-D locations in the map
        for i in range(m):
            for j in range(n):
                yield np.array([i, j])

    def train(self, input_vects, input_classes=None, test_vects=None, test_classes=None):
        """
        Trains the SOM.
        'input_vects' should be an iterable of 1-D NumPy arrays with
        dimensionality as provided during initialization of this SOM.
        Current weightage vectors for all neurons(initially random) are
        taken as starting conditions for training.
        """
        with self._sess:
            saver = tf.train.Saver()
            summary_writer = tf.summary.FileWriter(self.logs_path)
            for iter_no in range(self._n_iterations):
                if iter_no % 5 == 0:
                    print('Iteration {}'.format(iter_no))
                    # delta sanity check
                    delta = self._sess.run(self.weightage_delta, feed_dict={self._vect_input: input_vects[0:1],
                            self._iter_input: iter_no})
                    assert not np.any(np.isnan(delta))
                count = 0
                avg_delta = []
                num_batches = int(np.ceil(len(input_vects) / self.batch_size))
                for i in range(num_batches):
                    count = count + 1
                    start = self.batch_size * i
                    end = self.batch_size * (i+1)
                    _, a = self._sess.run([self._training_op, self.weightage_delta],
                                     feed_dict={self._vect_input: input_vects[start:end],
                                                self._iter_input: iter_no})
                    avg_delta.append(np.mean(a))
                    check_arr = a < 1e-28
                    if np.all(check_arr):
                        print('Warning: training seems to have converged - deltas extremely low.')
                    break
                avg_delta = np.mean(avg_delta)

                #Store a centroid grid for easy retrieval later on
                centroid_grid = [[] for i in range(self._m)]
                self._weightages = list(self._sess.run(self._weightage_vects))
                self._locations = list(self._sess.run(self._location_vects))

                #Run summaries
                if input_classes is not None:
                    train_comp = self.class_compactness(input_vects, input_classes)
                    #train_comp = [0]
                    train_mean_conv, train_var_conv, train_conv = self.population_based_convergence(input_vects)
                    print('train: mean {} var {} tot {}'.format(train_mean_conv, train_var_conv, train_conv))
                    #print(train_conv)
                else:
                    train_comp = [0]
                    train_conv = [0]
                if test_classes is not None:
                    test_comp = self.class_compactness(test_vects, test_classes)
                    #test_comp = [0]
                    test_mean_conv, test_var_conv, test_conv = self.population_based_convergence(test_vects)
                    print('test: mean {} var {} tot {}'.format(test_mean_conv, test_var_conv, test_conv))
                    #print(test_conv)
                else:
                    test_comp = [0]
                    test_conv = [0]
                summary = self._sess.run(self.summaries,
                                         feed_dict={self._train_compactness: train_comp,
                                                    self._test_compactness: test_comp,
                                                    self._train_population_convergence: train_conv,
                                                    self._test_population_convergence: test_conv,
                                                    self._train_mean_convergence: train_mean_conv,
                                                    self._test_mean_convergence: test_mean_conv,
                                                    self._train_var_convergence: train_var_conv,
                                                    self._test_var_convergence: test_var_conv,
                                                    self._avg_delta: avg_delta
                                                    })
                summary_writer.add_summary(summary, global_step=iter_no)

                #Save model periodically
                if iter_no % 5 == 0:
                    if not os.path.exists(self.checkpoint_dir):
                        os.makedirs(self.checkpoint_dir)
                    saver.save(self._sess,
                               os.path.join(self.checkpoint_dir,
                                            self.get_experiment_name(self.checkpoint_dir) + '_' + str(iter_no)+ 'epoch.ckpt'))
            for i, loc in enumerate(self._locations):
                centroid_grid[loc[0]].append(self._weightages[i])
            self._centroid_grid = centroid_grid

            self._trained = True

            # Save the final model
            if not os.path.exists(self.checkpoint_dir):
                os.makedirs(self.checkpoint_dir)
            saver.save(self._sess,
                       os.path.join(self.checkpoint_dir,
                                    self.get_experiment_name(self.checkpoint_dir) + '_final.ckpt'))

    def restore_trained(self):
        ckpt = tf.train.get_checkpoint_state(self.checkpoint_dir)
        if ckpt and ckpt.model_checkpoint_path:
            with self._sess:
              saver = tf.train.Saver()
              saver.restore(self._sess, ckpt.model_checkpoint_path)

              #restore usefull variable
              centroid_grid = [[] for i in range(self._m)]
              self._weightages = list(self._sess.run(self._weightage_vects))
              self._locations = list(self._sess.run(self._location_vects))
              for i, loc in enumerate(self._locations):
                  centroid_grid[loc[0]].append(self._weightages[i])
              self._centroid_grid = centroid_grid

              self._trained = True

              print('RESTORED SOM MODEL')
              return True
        else:
            print('NO CHECKPOINT FOUND')
            return False

    def get_experiment_name(self, data):
        return data + '_tau' + str(self.tau) + '_thrsh' \
               + str(self.threshold) + '_sigma' + str(self.sigma) + '_batch' + str(self.batch_size) \
               + '_alpha' + str(self.alpha)

    def get_centroids(self):
        """
        Returns a list of 'm' lists, with each inner list containing
        the 'n' corresponding centroid locations as 1-D NumPy arrays.
        """
        if not self._trained:
            raise ValueError("SOM not trained yet")
        return self._centroid_grid

    def map_vects(self, input_vects):
        """
        Maps each input vector to the relevant neuron in the SOM
        grid.
        'input_vects' should be an iterable of 1-D NumPy arrays with
        dimensionality as provided during initialization of this SOM.
        Returns a list of 1-D NumPy arrays containing (row, column)
        info for each input vector(in the same order), corresponding
        to mapped neuron.
        """

        if not self._trained:
            raise ValueError("SOM not trained yet")

        to_return = []
        for vect in input_vects:
            min_index = min([i for i in range(len(self._weightages))],
                            key=lambda x: np.linalg.norm(vect-
                                                         self._weightages[x]))
            to_return.append(self._locations[min_index])

        return to_return


    def get_BMU(self, input_vect):
        min_index = min([i for i in range(len(self._weightages))],
                            key=lambda x: np.linalg.norm(input_vect-
                                                         self._weightages[x]))

        return [min_index,self._locations[min_index]]

    def detect_superpositions(self, l):
        for l_i in l:
            if len(l_i) > 1:
                if all(x == l_i[0] for x in l_i) == False:
                    return True
        return False

    def memorize_examples_by_class(self, X, y):
        self.bmu_class_dict = {i : [] for i in range(self._n * self._m)}
        for i, (x, yi) in enumerate(zip(X, y)):
            activations, _ = self.get_activations(x, normalize=False, mode='exp', threshold=False)
            bmu_index = np.argmax(activations)
            self.bmu_class_dict[bmu_index].append(yi)
        superpositions = self.detect_superpositions(self.bmu_class_dict.values())
        print('More than a class mapped to a neuron: '+ str(superpositions))
        return superpositions

    def get_activations(self, input_vect, normalize=True, threshold=True, mode='exp'):
      # get activations for the word learning

  # Quantization error:
      activations = list()
      pos_activations = list()
      for i in range(len(self._weightages)):
          d = np.array([])

          d = (np.absolute(input_vect-self._weightages[i])).tolist()
          if mode == 'exp':
              activations.append(math.exp(-(np.sum(d)/len(d))/self.tau))
          if mode == 'linear':
              activations.append(1/np.sum(d))
          pos_activations.append(self._locations[i])
      activations = np.array(activations)
      if normalize:
          max_ = max(activations)
          min_ = min(activations)
          activations = (activations - min_) / float(max_ - min_)
      if threshold:
          idx = activations < self.threshold
          activations[idx] = 0
      return [activations,pos_activations]



    def plot_som(self, X, y, plot_name='som-viz.png'):
        image_grid = np.zeros(shape=(self._n,self._m))

        color_names = \
            {0: 'black', 1: 'blue', 2: 'skyblue',
             3: 'aqua', 4: 'darkgray', 5: 'green', 6: 'red',
             7: 'cyan', 8: 'violet', 9: 'yellow'}
        #Map colours to their closest neurons
        mapped = self.map_vects(X)

        #Plot
        plt.imshow(image_grid)
        plt.title('Color SOM')
        for i, m in enumerate(mapped):
            plt.text(m[1], m[0], color_names[y[i]], ha='center', va='center',
                     bbox=dict(facecolor=color_names[y[i]], alpha=0.5, lw=0))
        plt.savefig(os.path.join(Constants.PLOT_FOLDER, plot_name))

    ## TODO: la inter_class_distance può essere calcolata una sola volta per dataset
    @profile
    def class_compactness(self, xs, ys, train=True):
        class_belonging_dict = {y: [] for y in list(set(ys))}
        for i, y in enumerate(ys):
            class_belonging_dict[y].append(i)
        intra_class_distance = [0 for y in list(set(ys))]
        for y in set(ys):
            for index, j in enumerate(class_belonging_dict[y]):
                x1 = xs[j]
                for k in class_belonging_dict[y][index+1:]:
                    x2 = xs[k]
                    _, pos_x1 = self.get_BMU(x1)
                    _, pos_x2 = self.get_BMU(x2)
                    intra_class_distance[y] += np.linalg.norm(pos_x1-pos_x2)
        class_compactness = None
        if train == True:
            class_compactness = self.train_inter_class_distance
        else:
            class_compactness = self.test_inter_class_distance
        if class_compactness == None:
            for i, x1 in enumerate(xs):
                for j, x2 in enumerate(xs[i+1:]):
                    class_compactness += np.linalg.norm(x1-x2)
            class_compactness /= len(xs)
        if train == True:
            class_compactness = intra_class_distance/self.train_inter_class_distance
        else:
            class_compactness = intra_class_distance/self.test_inter_class_distance
        return class_compactness

    @profile
    def population_based_convergence(self, xs, alpha=0.10):
        '''
        Population based convergence is a feature-by-feature convergence criterion.
        This implementation is based on "A Convergence Criterion for Self-Organizing
        Maps" by B. Ott, 2012.

        Name mapping from variables to paper:
        data_feature_mean: $x^1$
        neuron_feature_mean: $x^2$
        data_feature_var: $\sigma^2_1$
        neuron_feature_var: $\sigma^2_2$
        num_samples: $n_1$
        num_neurons: $n_2$
        '''
        weights = self._sess.run(self._weightage_vects)
        data_feature_mean = np.mean(xs, axis=0)
        neuron_feature_mean = np.mean(weights, axis=0)
        data_feature_var = np.var(xs, axis=0)
        neuron_feature_var = np.var(weights, axis=0)
        num_samples = len(xs)
        num_neurons = (self._m * self._n)

        z = norm.ppf(q=1-(alpha/2))
        lhs = (data_feature_mean - neuron_feature_mean) \
              - z * np.sqrt(data_feature_var / num_samples + neuron_feature_var / num_neurons) # eq. 17 lhs
        rhs = (data_feature_mean - neuron_feature_mean) \
              + z * np.sqrt(data_feature_var / num_samples + neuron_feature_var / num_neurons) # eq. 17 rhs

        mean_stat = np.multiply(lhs, rhs)
        mean_pos_converged = np.where(mean_stat[mean_stat<0])[0]

        # std convergence
        fisher_f_stat = fisher_f.ppf(q=1-(alpha/2), dfn=num_samples-1, dfd=num_neurons-1)

        lhs = np.divide(data_feature_var, neuron_feature_var) * (1 / fisher_f_stat)
        rhs = np.divide(data_feature_var, neuron_feature_var) * fisher_f_stat

        lhs = (lhs <= 1).astype(int)
        rhs = (rhs >= 1).astype(int)
        var_stat = np.multiply(lhs, rhs)
        var_pos_converged = var_stat[var_stat != 0]

        print('Mean converged features: {}'.format(len(mean_pos_converged)))
        print('Current ratio: {}'.format(data_feature_var / neuron_feature_var))
        print('Average ratio: {}'.format(np.mean(data_feature_var / neuron_feature_var)))
        print('Var converged features: {}'.format(len(var_pos_converged)))

        # return normalized values for mean, variance and total convergence
        return len(mean_pos_converged) / len(neuron_feature_mean), \
               len(var_pos_converged) / len(neuron_feature_mean), \
               len(np.intersect1d(mean_pos_converged, var_pos_converged, assume_unique=True)) / len(neuron_feature_mean)



if __name__ == '__main__':
    pass
