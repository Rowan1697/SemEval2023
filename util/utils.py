import pandas as pd
import os
import torch 
import numpy as np
from tqdm import tqdm
import random
import evaluate
from colorama import Fore, Style, Back
os.environ["WANDB_DISABLED"] = "true"

metric_acc = evaluate.load("accuracy")
metric_f1 = evaluate.load("f1")

def get_tag_mappings():
    with open('../util/tags.txt','r') as file:
        unique_tags = [line.strip() for line in file]


    tags_to_ids = {k: v for v, k in enumerate(unique_tags)}
    ids_to_tags = {v: k for v, k in enumerate(unique_tags)}

    return tags_to_ids, ids_to_tags


tags_to_ids, ids_to_tags = get_tag_mappings()
number_of_labels = len(tags_to_ids)

def get_data(LANG, SET, train=True):

    exp = 'train' if train else 'dev'

    if SET !=None and LANG!=None:
        df = pd.read_csv(f'./Dataset/{exp}-wiki-{LANG}-{SET}.csv')
        df = df.drop(columns=['sent'])
        df = df.rename(columns={'augmented_sen':'sent'})

    elif SET !=None and LANG==None:
        data = os.listdir('./Dataset')
        dataframes = [pd.read_csv("./Dataset/"+file) for file in data if exp in file and SET in file]
        df = pd.concat(dataframes)
        df = df.drop(columns=['sent'])
        df = df.rename(columns={'augmented_sen':'sent'})
    else:
        df = pd.read_csv(f'./Dataset/{exp}.csv')

    return df

def get_data_from_hub(LANG, SET, split='validation'):

    from datasets import load_dataset
    dataset = load_dataset('garNER/custom-MultiCoNER-II', split=split)
    if LANG!=None:
        dataset = dataset.filter(lambda example: example['lang']==LANG)
    
    removed = ['None', 'tags', 'LM']
    if SET==None:
        SET='None'
    removed.remove(SET)
    dataset = dataset.remove_columns(removed)
    dataset = dataset.rename_columns({SET:'sent'})


    return dataset


def recreate_conll_format(data, col='labels'):

    id = data['ID']
    lang = data['lang']
    lines = [f'# id {id} \t domain={lang}']
    sents = data['sent'].split()
    labels = data[col].split()
    for token,label in zip(sents,labels):
        line = f'{token} _ _ {label}'
        lines.append(line)
    
    return "\n".join(lines)

def write_conll_format(fileName, dataframe, col='labels'):

    
    with open(fileName,'w') as file:
        for ind in range(dataframe.shape[0]):
            data = dataframe.iloc[ind]
            lines = recreate_conll_format(data, col)
            file.write("\n"+lines+"\n\n")






def compute_metrics_test(preds, labels, is_crf= False):
    

    tr_active_acc = labels != -100
    pr_active_acc = preds != -100

    tags = torch.masked_select(labels, tr_active_acc)
    if is_crf:
        predicts = torch.masked_select(preds, pr_active_acc)
    else:
        predicts = torch.masked_select(preds, tr_active_acc)

    # acc = metric_acc.compute(predictions=predicts, references=tags)
    # f1 = metric_f1.compute(predictions=predicts, references=tags, average='macro')
    
    return tags.tolist(), predicts.tolist()


def compute_metrics_crf(pred):
    """
    We're going to compute the accuracy and f1 score of the predictions made by the model
    
    :param pred: the output of the model
    """
    

    pred_logits = pred.predictions
    pred_ids = torch.tensor(pred_logits)

    tr_active_acc = torch.from_numpy(pred.label_ids != -100)
    pr_active_acc = torch.from_numpy(pred_logits != -100)

    train_tags = torch.masked_select(torch.from_numpy(pred.label_ids), tr_active_acc)
    train_predicts = torch.masked_select(pred_ids, pr_active_acc)

    acc = metric_acc.compute(predictions=train_predicts, references=train_tags)
    f1 = metric_f1.compute(predictions=train_predicts, references=train_tags, average='macro')
    
    return {'accuracy': acc['accuracy'], 'f1':f1['f1']}

def compute_metrics(pred):
    """
    It takes the predictions from the model and computes the accuracy and f1 score
    
    :param pred: the prediction object returned by the model
    """
    
    
    pred_logits = pred.predictions
    pred_ids = torch.from_numpy(np.argmax(pred_logits, axis=-1))

    tr_active_acc = torch.from_numpy(pred.label_ids != -100)

    train_tags = torch.masked_select(torch.from_numpy(pred.label_ids), tr_active_acc)
    train_predicts = torch.masked_select(pred_ids, tr_active_acc)

    acc = metric_acc.compute(predictions=train_predicts, references=train_tags)
    f1 = metric_f1.compute(predictions=train_predicts, references=train_tags, average='macro')
    
    return {'accuracy': acc['accuracy'], 'f1':f1['f1']}


def print_predictions(tokens, pred_tags, true_tags):
    

    tokens = tokens.split()
    pred_tags = [ids_to_tags[idx] for idx in pred_tags if idx!=-100]
    true_tags = [ids_to_tags[idx] for idx in true_tags if idx!=-100]
    
    
    # if len(tokens) != len(pred_tags):
    #     print(tokens)
    #     return " "
    
    output = []
    
    
    for t,tl,pl in zip(tokens[:len(true_tags)],true_tags,pred_tags):

        if tl == pl:
            o = f"{t} {Back.GREEN}[{tl}][{pl}]{Style.RESET_ALL}"

        else:
            o = f"{t} {Back.GREEN}[{tl}]{Style.RESET_ALL}{Back.RED}[{pl}]{Style.RESET_ALL}"

        output.append(o)
        
    return " ".join(output)," ".join(pred_tags), " ".join(true_tags)


def feval(test_data, test_tokenized, model, device, IS_CRF=False):

    visualization = []
    outputs = []
    all_true = []
    all_pred = []


    test_len = len(test_tokenized)

    for i in tqdm(range(test_len)): 

        inp_ids = torch.as_tensor([test_tokenized[i]["input_ids"]]).to(device)
   
        label_ids = torch.as_tensor([test_tokenized[i]["labels"]]).to(device)
        
        mask = torch.as_tensor([test_tokenized[i]["attention_mask"]]).to(device)

        if IS_CRF:
            pred_ids = model(input_ids=inp_ids, attention_mask=mask, labels=label_ids)['logits']
        else:
            logits = model(input_ids=inp_ids, attention_mask=mask).logits
            pred_ids = torch.argmax(logits, dim=-1)[0]

        # pred_ids = model(input_ids=inp_ids, attention_mask=mask, labels=label_ids)['logits']
        
        tags, predicts = compute_metrics_test(pred_ids,label_ids, IS_CRF)

        all_true.extend(tags)
        all_pred.extend(predicts)
        
        vis, pred_tags, true_tags = print_predictions(test_data[i]['sent'],predicts,tags)
        
        outputs.append((test_data[i]['ID'],test_data[i]['lang'], test_data[i]['sent'], pred_tags, true_tags))
        
        # acc += result['accuracy']
        # f1 += result['f1']
        visualization.append(vis)
        
    #     print(output)
    #     break
        
        
    acc = metric_acc.compute(predictions=all_pred, references=all_true)['accuracy']
    f1 = metric_f1.compute(predictions=all_pred, references=all_true, average='macro')['f1']
    print(f'Accuracy: {acc}')
    print(f'F1: {f1}')

    return outputs, visualization