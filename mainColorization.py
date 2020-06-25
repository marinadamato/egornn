from __future__ import print_function, division
from spatial_transforms import (Compose, ToTensor, CenterCrop, Scale, Normalize, MultiScaleCornerCrop,
                                RandomHorizontalFlip)
from tensorboardX import SummaryWriter
import torch.nn as nn
from torch.autograd import Variable
from makeDatasetColorization import *
from colorization_block import colorization
import argparse
import sys


def main_run(dataset, trainDir, valDir, outDir, stackSize, trainBatchSize, valBatchSize, numEpochs, lr1,
             decay_factor, decay_step, memSize,color_dict,stage1_dict):


    if dataset == 'gtea61':
        num_classes = 61
    elif dataset == 'gtea71':
      num_classes = 71
    elif dataset == 'gtea_gaze':
        num_classes = 44
    elif dataset == 'egtea':
        num_classes = 106
    else:
        print('Dataset not found')
        sys.exit()

    min_accuracy = 0

    model_folder = os.path.join('./', outDir, dataset, 'Color','after')  # Dir for saving models and log files
    # Create the dir
    if os.path.exists(model_folder):
        print('Dir {} exists!'.format(model_folder))
        sys.exit()
    os.makedirs(model_folder)

    # Log files
    writer = SummaryWriter(model_folder)
    train_log_loss = open((model_folder + '/train_log_loss.txt'), 'w')
    train_log_acc = open((model_folder + '/train_log_acc.txt'), 'w')
    val_log_loss = open((model_folder + '/val_log_loss.txt'), 'w')
    val_log_acc = open((model_folder + '/val_log_acc.txt'), 'w')


    # Data loader
    normalize = Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])

    spatial_transform = Compose([Scale(256), RandomHorizontalFlip(), MultiScaleCornerCrop([1, 0.875, 0.75, 0.65625], 224),
                                 ToTensor(), normalize])

    vid_seq_train = makeDataset(trainDir, spatial_transform=spatial_transform, sequence=False,
                                stackSize=stackSize, fmt='.png')

    train_loader = torch.utils.data.DataLoader(vid_seq_train, batch_size=trainBatchSize,
                            shuffle=True, sampler=None, num_workers=4, pin_memory=True)
    if valDir is not None:

        vid_seq_val = makeDataset(valDir, spatial_transform=Compose([Scale(256), CenterCrop(224), ToTensor(), normalize]),
                                   sequence=False, stackSize=stackSize, fmt='.png', phase='Test')

        val_loader = torch.utils.data.DataLoader(vid_seq_val, batch_size=valBatchSize,
                                shuffle=False, num_workers=2, pin_memory=True)
        valInstances = vid_seq_val.__len__()


    trainInstances = vid_seq_train.__len__()
    print('Number of samples in the dataset: training = {} | validation = {}'.format(trainInstances, valInstances))

    model = colorization(num_classes=num_classes)
    
    model.RGBnet.load_state_dict(torch.load(stage1_dict))
    model.train(True)
    model.RGBnet.train(False)
    
    train_params =[]

    for params in model.parameters():
        params.requires_grad = True
        train_params += [params]
    for params in model.RGBnet.parameters():
        params.requires_grad = False

    model.cuda()

    loss_fn = nn.CrossEntropyLoss()

    optimizer_fn = torch.optim.Adam(train_params, lr=lr1, weight_decay=5e-4)

    optim_scheduler = torch.optim.lr_scheduler.MultiStepLR(optimizer_fn, milestones=decay_step, gamma=decay_factor)

    train_iter = 0

    for epoch in range(numEpochs):
        
        epoch_loss = 0
        numCorrTrain = 0
        trainSamples = 0
        iterPerEpoch = 0
        model.train(True)
        model.RGBnet.train(False)
        writer.add_scalar('lr', optimizer_fn.param_groups[0]['lr'], epoch+1)
        for i, (inputVariable, labelVariable) in enumerate(train_loader):
            train_iter += 1
            iterPerEpoch += 1
            inputVariable =inputVariable.permute(1,0,2,3,4).cuda()
            labelVariable =labelVariable.cuda()
            optimizer_fn.zero_grad()
            trainSamples += inputVariable.size(0)
            output_label, _ = model(inputVariable)
            loss = loss_fn(output_label, labelVariable)
            loss.backward()
            
            _, predicted = torch.max(output_label.data, 1)
            numCorrTrain += torch.sum(predicted == labelVariable.data).data.item()
            epoch_loss += loss.item()
            optimizer_fn.step()
        avg_loss = epoch_loss/iterPerEpoch
        trainAccuracy = (numCorrTrain / trainSamples) * 100
        print('Train: Epoch = {} | Loss = {} | Accuracy = {}'.format(epoch + 1, avg_loss, trainAccuracy))
        writer.add_scalar('train/epoch_loss', avg_loss, epoch+1)
        writer.add_scalar('train/accuracy', trainAccuracy, epoch+1)
        train_log_loss.write('Training loss after {} epoch = {}\n'.format(epoch+1, avg_loss))
        train_log_acc.write('Training accuracy after {} epoch = {}\n'.format(epoch+1, trainAccuracy))
        
        optim_scheduler.step()
        if valDir is not None:
            if (epoch+1) % 1 == 0:
                model.train(False)
                val_loss_epoch = 0
                val_iter = 0
                val_samples = 0
                numCorr = 0
                f_print=0
                for j, (inputVariable, labelVariable) in enumerate(val_loader):
                    val_iter += 1
                    val_samples += inputVariable.size(0)
                    inputVariable =inputVariable.permute(1,0,2,3,4).cuda()
                    labelVariable =labelVariable.cuda()
                    if epoch%10==1:f_print=1
                    output_label, _ = model(inputVariable,f_print)
                    f_print=0
                    val_loss = loss_fn(output_label, labelVariable)
                    val_loss_epoch += val_loss.item()
                    _, predicted = torch.max(output_label.data, 1)
                    numCorr += torch.sum(predicted == labelVariable.data).data.item()
                val_accuracy = (numCorr / val_samples) * 100
                avg_val_loss = val_loss_epoch / val_iter
                print('Validation: Epoch = {} | Loss = {} | Accuracy = {}'.format(epoch + 1, avg_val_loss, val_accuracy))
                writer.add_scalar('val/epoch_loss', avg_val_loss, epoch + 1)
                writer.add_scalar('val/accuracy', val_accuracy, epoch + 1)
                val_log_loss.write('Val Loss after {} epochs = {}\n'.format(epoch + 1, avg_val_loss))
                val_log_acc.write('Val Accuracy after {} epochs = {}%\n'.format(epoch + 1, val_accuracy))
                if epoch%10 ==0:
                    save_path_model = (model_folder + '/model_flow_state_dict.pth')
                    torch.save(model.state_dict(), save_path_model)
                    min_accuracy = val_accuracy
            else:
                if (epoch+1) % 10 == 0:
                    save_path_model = (model_folder + '/model_flow_state_dict_epoch' + str(epoch+1) + '.pth')
                    torch.save(model.state_dict(), save_path_model)

    train_log_loss.close()
    train_log_acc.close()
    val_log_acc.close()
    val_log_loss.close()
    writer.export_scalars_to_json(model_folder + "/all_scalars.json")
    writer.close()
    
    


def __main__():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', type=str, default='gtea61', help='Dataset')
    parser.add_argument('--trainDatasetDir', type=str, default='./dataset/gtea_warped_flow_61/split2/train',
                        help='Train set directory')
    parser.add_argument('--valDatasetDir', type=str, default=None,
                        help='Validation set directory')
    parser.add_argument('--outDir', type=str, default='experiments', help='Directory to save results')
    parser.add_argument('--stage1Dict', type=str, default='./experiments/gtea61/rgb/stage1/best_model_state_dict.pth',
                        help='Stage 1 model path')
    parser.add_argument('--color_dict', type=str, default='./experiments/gtea61/rgb/stage1/best_model_state_dict.pth',
                        help='Stage 1 model path')
    parser.add_argument('--stackSize', type=int, default=5, help='Length of sequence')
    parser.add_argument('--trainBatchSize', type=int, default=32, help='Training batch size')
    parser.add_argument('--valBatchSize', type=int, default=8, help='Validation batch size')
    parser.add_argument('--numEpochs', type=int, default=750, help='Number of epochs')
    parser.add_argument('--lr', type=float, default=1e-2, help='Learning rate')
    parser.add_argument('--stepSize', type=float, default=[150, 300, 500], nargs="+", help='Learning rate decay step')
    parser.add_argument('--decayRate', type=float, default=0.5, help='Learning rate decay rate')
    parser.add_argument('--memSize', type=int, default=512, help='ConvLSTM hidden state size')

    args = parser.parse_args()

    dataset = args.dataset
    trainDatasetDir = args.trainDatasetDir
    valDatasetDir = args.valDatasetDir
    outDir = args.outDir
    stackSize = args.stackSize
    trainBatchSize = args.trainBatchSize
    valBatchSize = args.valBatchSize
    numEpochs = args.numEpochs
    lr1 = args.lr
    stepSize = args.stepSize
    decayRate = args.decayRate
    memSize = args.memSize
    color_dict =args.color_dict
    stage1_dict= args.stage1Dict

    main_run(dataset, trainDatasetDir, valDatasetDir, outDir, stackSize, trainBatchSize, valBatchSize, numEpochs, lr1,
             decayRate, stepSize, memSize,color_dict,stage1_dict)

__main__()
