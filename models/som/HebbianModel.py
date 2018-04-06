import tensorflow as tf
import numpy as np
import os
import sys
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams.update({'font.size': 8})
import matplotlib.pyplot as plt
from RepresentationExperiments.distance_experiments import get_prototypes
from sklearn.preprocessing import MinMaxScaler
from utils.constants import Constants

class HebbianModel(object):

    def __init__(self, som_a, som_v, a_dim, v_dim, learning_rate=10,
                 n_presentations=1, n_classes=10, threshold=.6, tau=0.5,
                 checkpoint_dir=None):
        assert som_a._m == som_v._m and som_a._n == som_v._n
        self.num_neurons = som_a._m * som_a._n
        self._graph = tf.Graph()
        self.som_a = som_a
        self.som_v = som_v
        self.a_dim = a_dim
        self.v_dim = v_dim
        self.n_presentations = n_presentations
        self.n_classes = n_classes
        self.checkpoint_dir = checkpoint_dir
        self.learning_rate = learning_rate
        self.threshold = threshold
        self.tau = tau
        self._trained = False

        with self._graph.as_default():
            self.weights = tf.Variable(
                             tf.random_normal([self.num_neurons, self.num_neurons],
                             mean=1/self.num_neurons,
                             stddev=1/np.sqrt(1000*self.num_neurons))
                           )

            self.activation_a = tf.placeholder(dtype=tf.float32, shape=[self.num_neurons])
            self.activation_v = tf.placeholder(dtype=tf.float32, shape=[self.num_neurons])
            self.assigned_weights = tf.placeholder(dtype=tf.float32, shape=[self.num_neurons, self.num_neurons])

            self.delta = 1 - tf.exp(-self.learning_rate * tf.matmul(tf.reshape(self.activation_a, (-1, 1)), tf.reshape(self.activation_v, (1, -1))))
            new_weights = tf.add(self.weights, self.delta)
            self.training = tf.assign(self.weights, new_weights)

            self.assign_op = tf.assign(self.weights, self.assigned_weights)

            self._sess  = tf.Session()
            init_op = tf.global_variables_initializer()
            self._sess.run(init_op)

    def train(self, input_a, input_v):
        '''
        input_a: list containing a number of training examples equal to
                 self.n_presentations
        input_v : same as above

        This function will raise an AssertionError if:
        * len(input_a) != len(input_v)
        * len(input_a) != self.n_presentations * self.n_classes
        The first property assures we have a sane number of examples for both
        SOMs, while the second one ensures that the model has an example
        from each class to be trained on.
        '''
        assert len(input_a) == len(input_v) == self.n_presentations * self.n_classes, \
               'Number of training examples and number of desired presentations \
                is incoherent. len(input_a) = {}; len(input_v) = {}; \
                n_presentations = {}, n_classes = {}'.format(len(input_a), len(input_v),
                                                      self.n_presentations, self.n_classes)
        with self._sess:
            # present images to model
            for i in range(len(input_a)):
                # get activations from som
                activation_a, _ = self.som_a.get_activations(input_a[i])
                activation_v, _ = self.som_v.get_activations(input_v[i])

                # run training op
                _, d = self._sess.run([self.training, self.delta],
                                      feed_dict={self.activation_a: activation_a,
                                                 self.activation_v: activation_v})

            # normalize sum of weights to 1
            w = self._sess.run(self.weights)
            w = w.flatten()
            w_sum = np.sum(w)
            w_norm = [wi / w_sum for wi in w]
            w = np.reshape(w_norm, (self.num_neurons, self.num_neurons))

            self._sess.run(self.assign_op, feed_dict={self.assigned_weights: w})
            self._trained = True

            # save to checkpoint_dir
            if self.checkpoint_dir != None:
                saver = tf.train.Saver()
                if not os.path.exists(self.checkpoint_dir):
                    os.makedirs(self.checkpoint_dir)
                saver.save(self._sess,
                           os.path.join(self.checkpoint_dir,
                                       'model.ckpt'),
                           1)

            # convert weights to numpy arrays from tf tensors
            self.weights = self._sess.run(self.weights)

    def restore_trained(self):
        ckpt = tf.train.get_checkpoint_state(self.checkpoint_dir)
        if ckpt and ckpt.model_checkpoint_path:
            with self._sess:
              saver = tf.train.Saver()
              saver.restore(self._sess, ckpt.model_checkpoint_path)
              self.weights = self._sess.run(self.weights)
              print('RESTORED HEBBIAN MODEL')
              return True
        else:
            print('NO CHECKPOINT FOUND')
            return False


    def get_bmus_propagate(self, x, source_som='v'):
        '''
        Get the best matching unit by propagating an input vector's activations
        to the other SOM. More specifically, we use the synapses connected to the
        source som's BMU to find a matching BMU in the target som.

        x: input vector. Must have a compatible size with the som described in
           'source_som' parameter
        source_som: a string representing the source som. If 'a', the activations
        of the audio som will be propagated to the visual one; if 'v', the opposite
        will happen.
        '''
        if source_som == 'v':
            from_som = self.som_v
            to_som = self.som_a
        elif source_som == 'a':
            from_som = self.som_a
            to_som = self.som_v
        else:
            raise ValueError('Wrong string for source_som parameter')
        source_activation, _ = from_som.get_activations(x)
        source_bmu_index = np.argmax(np.array(source_activation))
        #bmu_weights = self._sess.run(source_som._weightage_vects[bmu_index]) # probably un-needed?
        #if source_som == 'a':
        #    hebbian_weights = self.weights[:][source_bmu_index]
        #else:
        #    hebbian_weights = self.weights[source_bmu_index][:]
        #target_activation = hebbian_weights * source_activation
        source_activation = np.array(source_activation).reshape((-1, 1))
        if source_som == 'a':
            target_activation = np.matmul(self.weights.T, np.array(source_activation).reshape((-1, 1)))
        else:
            target_activation = np.matmul(self.weights, np.array(source_activation).reshape((-1, 1)))
        try:
            assert target_activation.shape[0] == (to_som._n * to_som._m)
        except AssertionError:
            print('Shapes do not match. target_activation: {};\
       som: {}'.format(target_activation.shape, to_som._n * to_som._m))
            sys.exit(1)
        target_bmu_index = np.argmax(target_activation)

        return source_bmu_index, target_bmu_index

    def evaluate(self, X_a, X_v, y_a, y_v, source='v', img_path=None):
        if source == 'v':
            X_source = X_v
            X_target = X_a
            y_source = y_v
            y_target = y_a
            source_som = self.som_v
            target_som = self.som_a
        elif source == 'a':
            X_source = X_a
            X_target = X_v
            y_source = y_a
            y_target = y_v
            source_som = self.som_a
            target_som = self.som_v
        else:
            raise ValueError('Wrong string for source parameter')

        y_pred = []
        img_n = 0

        for x, y in zip(X_source, y_source):
            source_bmu, target_bmu = self.get_bmus_propagate(x, source_som=source)
            target_activations = []
            target_bmu_weights = np.reshape(target_som._weightages[target_bmu],
                                           (1, -1))
            for yi_target, xi_target in zip(y_target, X_target):
                xi_target = np.reshape(xi_target, (-1, 1))
                activation = np.dot(target_bmu_weights, xi_target)
                # alternative way to compute the activation. should be the same performance wise. (untested)
                # activation = np.absolute(reference_representation - target_bmu_weights)
                # activation = np.exp(-(np.sum(activation)/len(activation))/self.tau)
                # save a correct example for later visualization, if necessary
                if yi_target == y:
                    xi_true = xi_target
                # the float cast is so that 'activation' is not seen as an array but as an element
                target_activations.append(float(activation))
            yi_pred_idx = np.argmax(target_activations)
            yi_pred = y_target[yi_pred_idx]
            y_pred.append(yi_pred)
            # image generation code
            if img_path != None:
                if source == 'a':
                    hebbian_weights = self.weights[:][source_bmu]
                else:
                    hebbian_weights = self.weights[source_bmu][:]

                source_activation, _ = source_som.get_activations(x)
                target_activation_true, _ = target_som.get_activations(xi_true)
                target_activation_pred, _ = target_som.get_activations(X_target[yi_pred_idx])
                #propagated_activation = hebbian_weights * source_activation
                if source == 'a':
                    propagated_activation = np.matmul(self.weights.T, np.array(source_activation).reshape((-1, 1)))
                else:
                    propagated_activation = np.matmul(self.weights, np.array(source_activation).reshape((-1, 1)))

                fig, axis_arr = plt.subplots(3, 2)
                axis_arr[0, 0].matshow(np.array(source_activation)
                                       .reshape((source_som._m, source_som._n)))
                axis_arr[0, 0].set_title('Source SOM activation')
                axis_arr[0, 1].matshow(propagated_activation
                                       .reshape((source_som._m, source_som._n)))
                axis_arr[0, 1].set_title('Propagation of activation to target')
                axis_arr[1, 0].matshow(np.array(target_activation_true)
                                       .reshape((source_som._m, source_som._n)))
                axis_arr[1, 0].set_title('Target SOM activation true label ({})'.format(y))
                axis_arr[1, 1].matshow(np.array(target_activation_pred)
                                       .reshape((source_som._m, source_som._n)))
                axis_arr[1, 1].set_title('Target SOM activation predicted label ({})'.format(yi_pred))
                axis_arr[2, 1].matshow(np.array(hebbian_weights)
                                       .reshape((source_som._m, source_som._n)))
                axis_arr[2, 1].set_title('Hebbian weights of source BMU')
                axis_arr[2, 0].matshow(np.zeros((source_som._m, source_som._n)))
                plt.tight_layout()
                plt.savefig(os.path.join(Constants.PLOT_FOLDER, str(img_n)+'.png'))
                plt.clf()
                img_n += 1

        correct = 0
        for yi, yj in zip(y_pred, y_source):
            if yi == yj:
                correct += 1
        print('correct: {}' .format(correct))
        print(y_source)
        print(y_pred)
        return correct/len(y_pred)

    def threshold_activation(self, x):
        idx = x < self.threshold
        x[idx] = 0
        return x

# some test cases. do not use as an entry point for experiments!
if __name__ == '__main__':
    pass