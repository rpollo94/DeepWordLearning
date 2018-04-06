from models.som.SOM import SOM
from models.som.HebbianModel import HebbianModel
from utils.constants import Constants
from utils.utils import from_csv_with_filenames, from_csv_visual, from_csv, to_csv
from sklearn.utils import shuffle
from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import train_test_split
import os
import numpy as np

soma_path = os.path.join(Constants.DATA_FOLDER, '10classes', 'audio_model_25t', '')
somv_path = os.path.join(Constants.DATA_FOLDER, '10classes', 'visual_model_tau', '')
hebbian_path = os.path.join(Constants.DATA_FOLDER, '10classes', 'hebbian_model', '')
audio_data_path = os.path.join(Constants.DATA_FOLDER,
                               '10classes',
                               'audio_data_25t.csv')
visual_data_path = os.path.join(Constants.DATA_FOLDER,
                                '10classes',
                                'VisualInputTrainingSet.csv')

def create_folds(a_xs, v_xs, a_ys, v_ys, n_folds=1, n_classes=10):
    '''
    In this context, a fold is an array of data that has n_folds examples
    from each class.
    '''
    #assert len(a_xs) == len(v_xs) == len(a_ys) == len(v_ys)
    assert n_folds * n_classes <= len(a_xs)
    ind = a_ys.argsort()
    a_xs = a_xs[ind]
    a_ys = a_ys[ind]
    ind = v_ys.argsort()
    v_xs = v_xs[ind]
    v_ys = v_ys[ind]
    # note that a_xs_ is not a_xs
    a_xs_ = [a_x for a_x in a_xs]
    a_ys_ = [a_y for a_y in a_ys]
    v_xs_ = [v_x for v_x in v_xs]
    v_ys_ = [v_y for v_y in v_ys]
    a_xs_fold = []
    a_ys_fold = []
    v_xs_fold = []
    v_ys_fold = []
    for i in range(n_folds):
        for c in range(n_classes):
            a_idx = a_ys_.index(c)
            v_idx = v_ys_.index(c)
            a_xs_fold.append(a_xs_[a_idx])
            a_ys_fold.append(c)
            v_xs_fold.append(v_xs_[v_idx])
            v_ys_fold.append(c)
            # delete elements so that they are not found again
            # and put in other folds
            del a_xs_[a_idx]
            del a_ys_[a_idx]
            del v_xs_[v_idx]
            del v_ys_[v_idx]
    return a_xs_fold, v_xs_fold, a_ys_fold, v_ys_fold


if __name__ == '__main__':
    a_xs, a_ys, _ = from_csv_with_filenames(audio_data_path)
    v_xs, v_ys = from_csv_visual(visual_data_path)
    # fix labels to 0-9 range
    a_ys = [int(y)-1000 for y in a_ys]
    v_ys = [int(y)-1000 for y in v_ys]
    # scale data to 0-1 range
    a_xs = MinMaxScaler().fit_transform(a_xs)
    v_xs = MinMaxScaler().fit_transform(v_xs)
    a_dim = len(a_xs[0])
    v_dim = len(v_xs[0])
    som_a = SOM(20, 30, a_dim, checkpoint_dir=soma_path, n_iterations=200,
                tau=0.1, threshold=0.6)
    som_v = SOM(20, 30, v_dim, checkpoint_dir=somv_path, n_iterations=200,
                tau=0.1, threshold=0.6)
    som_a.restore_trained()
    som_v.restore_trained()
    v_ys = np.array(v_ys)
    v_xs = np.array(v_xs)
    a_xs = np.array(a_xs)
    a_ys = np.array(a_ys)
    a_xs_train, a_xs_test, a_ys_train, a_ys_test = train_test_split(a_xs, a_ys, test_size=0.2)
    v_xs_train, v_xs_test, v_ys_train, v_ys_test = train_test_split(v_xs, v_ys, test_size=0.2)
    for n in range(1, 15):
        hebbian_model = HebbianModel(som_a, som_v, a_dim=a_dim,
                                     v_dim=v_dim, n_presentations=n,
                                     checkpoint_dir=hebbian_path,
                                     tau=0.1, learning_rate=100)
        # create em folds
        a_xs_fold, v_xs_fold, a_ys_fold, v_ys_fold = create_folds(a_xs_train, v_xs_train, a_ys_train, v_ys_train, n_folds=n)
        print('Training...')
        hebbian_model.train(a_xs_fold, v_xs_fold)
        print('Evaluating...')
        accuracy = hebbian_model.evaluate(a_xs_test, v_xs_test, a_ys_test, v_ys_test, source='v')
        print('n={}, accuracy={}'.format(n, accuracy))
