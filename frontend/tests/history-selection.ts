import {expect,type Page} from '@playwright/test'

export async function selectHistoryTask(page:Page,side:number,id:string){
 const column=page.getByTestId('ab-side').nth(side)
 const select=column.getByRole('combobox',{name:side===0?'实验A已完成任务':'实验B已完成任务',exact:true})
 await expect(select).toBeEnabled()
 await select.click()
 await select.fill(id)
 await page.getByRole('listbox',{name:side===0?'实验A已完成任务':'实验B已完成任务',exact:true}).getByTestId('run-option-'+id).click()
 await expect(column.getByTestId('history-result')).toContainText(id)
}
